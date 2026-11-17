/**
 * Ordered, cancellable speech playback.
 *
 * The backend synthesises one WAV per request and has a request-size limit, so
 * a long answer is split into bounded chunks and played strictly in order.
 * Every playback owns a monotonically increasing generation:
 *
 *  - ``stop()`` bumps the generation, aborts the in-flight fetch, pauses and
 *    clears the current ``Audio`` element and revokes its object URL.
 *  - A fetch that resolves after ``stop()`` (or after a newer playback began)
 *    is discarded, so a late fragment can never play out of turn.
 *  - ``blocked`` is reported when the browser refuses to start playback; the UI
 *    then offers an explicit unlock action instead of pretending to speak.
 */

import { isAbortError } from "./errors";

export type SpeechState = "idle" | "loading" | "playing" | "blocked" | "error";

export interface SpeechRequest {
  text: string;
  voice?: string;
  speed: number;
  /** Stable per-turn identifier used for diagnostics and late-result checks. */
  audioId?: string;
}

export interface SpeechQueueOptions {
  fetchAudio: (
    text: string,
    options: { voice?: string; speed: number; signal: AbortSignal },
  ) => Promise<Blob>;
  createObjectUrl?: (blob: Blob) => string;
  revokeObjectUrl?: (url: string) => void;
  createAudioElement?: (url: string) => HTMLAudioElement;
  chunkSize?: number;
  onState?: (state: SpeechState, detail?: string) => void;
}

export interface SpeechQueue {
  play(request: SpeechRequest): void;
  stop(): void;
  unlock(): Promise<boolean>;
  dispose(): void;
  getState(): SpeechState;
  isBusy(): boolean;
}

export const DEFAULT_SPEECH_CHUNK_SIZE = 2800;

/**
 * A very short silent WAV used only to satisfy the browser's autoplay policy
 * from inside a user gesture. It is never played through the speakers audibly.
 */
const SILENT_WAV_DATA_URL =
  "data:audio/wav;base64,UklGRsQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YaAAAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA";

export function splitSpeechText(text: string, size = DEFAULT_SPEECH_CHUNK_SIZE): string[] {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return [];
  if (clean.length <= size) return [clean];

  const chunks: string[] = [];
  let rest = clean;
  while (rest.length > size) {
    let cut = rest.lastIndexOf(" ", size);
    if (cut <= 0) cut = size;
    const head = rest.slice(0, cut).trim();
    if (head) chunks.push(head);
    rest = rest.slice(cut).trim();
  }
  if (rest) chunks.push(rest);
  return chunks;
}

function classifyPlaybackError(reason: unknown): "blocked" | "error" {
  const name = isAbortError(reason)
    ? "AbortError"
    : reason && typeof reason === "object" && "name" in reason
      ? String((reason as { name?: unknown }).name ?? "")
      : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "blocked";
  return "error";
}

function waitForPlayback(
  audio: HTMLAudioElement,
  signal: AbortSignal,
): Promise<"ended" | "blocked" | "error" | "aborted"> {
  return new Promise((resolve) => {
    let settled = false;
    const cleanup = () => {
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
      signal.removeEventListener("abort", onAbort);
    };
    const finish = (result: "ended" | "blocked" | "error" | "aborted") => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(result);
    };
    const onEnded = () => finish("ended");
    const onError = () => finish("error");
    const onAbort = () => finish("aborted");

    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);

    if (signal.aborted) {
      finish("aborted");
      return;
    }
    signal.addEventListener("abort", onAbort, { once: true });

    let started: Promise<void> | undefined;
    try {
      started = audio.play();
    } catch (reason) {
      finish(classifyPlaybackError(reason));
      return;
    }
    if (started && typeof started.then === "function") {
      started.catch((reason: unknown) => finish(classifyPlaybackError(reason)));
    }
  });
}

type AudioContextConstructor = new () => AudioContext;

function audioContextConstructor(): AudioContextConstructor | null {
  if (typeof window === "undefined") return null;
  const candidate =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext;
  return typeof candidate === "function" ? candidate : null;
}

export function createSpeechQueue(options: SpeechQueueOptions): SpeechQueue {
  const chunkSize = options.chunkSize && options.chunkSize > 0
    ? Math.floor(options.chunkSize)
    : DEFAULT_SPEECH_CHUNK_SIZE;
  const createObjectUrl = options.createObjectUrl
    ?? ((blob: Blob) => URL.createObjectURL(blob));
  const revokeObjectUrl = options.revokeObjectUrl
    ?? ((url: string) => URL.revokeObjectURL(url));
  const createAudioElement = options.createAudioElement
    ?? ((url: string) => new Audio(url));

  let generation = 0;
  let state: SpeechState = "idle";
  let controller: AbortController | null = null;
  let audio: HTMLAudioElement | null = null;
  let objectUrl: string | null = null;
  let pending: SpeechRequest | null = null;
  let disposed = false;

  const setState = (next: SpeechState, detail?: string) => {
    if (state === next) return;
    state = next;
    options.onState?.(next, detail);
  };

  const clearAudio = () => {
    const element = audio;
    const url = objectUrl;
    audio = null;
    objectUrl = null;
    if (element) {
      try {
        element.pause();
      } catch {
        /* Ignore pause failures on an already-detached element. */
      }
      try {
        element.removeAttribute("src");
      } catch {
        /* Ignore. */
      }
      try {
        element.src = "";
      } catch {
        /* Ignore. */
      }
      try {
        element.load?.();
      } catch {
        /* jsdom and some browsers do not implement load(). */
      }
    }
    if (url) {
      try {
        revokeObjectUrl(url);
      } catch {
        /* Revocation is best-effort. */
      }
    }
  };

  const isCurrent = (expected: number) => !disposed && expected === generation;

  const run = async (expected: number, request: SpeechRequest, chunks: string[]) => {
    for (const chunk of chunks) {
      if (!isCurrent(expected)) return;

      setState("loading");
      const chunkController = new AbortController();
      controller = chunkController;

      let blob: Blob;
      try {
        blob = await options.fetchAudio(chunk, {
          voice: request.voice,
          speed: request.speed,
          signal: chunkController.signal,
        });
      } catch (reason) {
        if (!isCurrent(expected) || isAbortError(reason)) return;
        const message = reason instanceof Error && reason.message
          ? reason.message
          : "A síntese de voz falhou.";
        setState("error", message);
        return;
      }

      // A newer play()/stop() may have happened while the request was in flight.
      if (!isCurrent(expected)) return;
      if (!blob || blob.size === 0) {
        setState("error", "O áudio devolvido está vazio.");
        return;
      }

      const url = createObjectUrl(blob);
      const element = createAudioElement(url);
      objectUrl = url;
      audio = element;
      setState("playing");

      const outcome = await waitForPlayback(element, chunkController.signal);
      if (!isCurrent(expected) || outcome === "aborted") {
        clearAudio();
        return;
      }
      if (outcome === "blocked") {
        setState("blocked");
        return;
      }
      if (outcome === "error") {
        setState("error", "Não consegui reproduzir o áudio gerado.");
        clearAudio();
        return;
      }
      clearAudio();
    }

    if (!isCurrent(expected)) return;
    pending = null;
    setState("idle");
  };

  const play = (request: SpeechRequest) => {
    if (disposed) return;
    stop();
    const expected = generation;
    const chunks = splitSpeechText(request.text, chunkSize);
    if (chunks.length === 0) {
      setState("idle");
      return;
    }
    pending = request;
    void run(expected, request, chunks);
  };

  const stop = () => {
    generation += 1;
    pending = null;
    const active = controller;
    controller = null;
    if (active) {
      try {
        active.abort();
      } catch {
        /* Ignore. */
      }
    }
    clearAudio();
    setState("idle");
  };

  const unlock = async (): Promise<boolean> => {
    let unlocked = false;
    if (typeof Audio !== "undefined") {
      try {
        const primer = new Audio(SILENT_WAV_DATA_URL);
        primer.muted = true;
        await primer.play();
        try {
          primer.pause();
          primer.removeAttribute("src");
        } catch {
          /* Ignore cleanup. */
        }
        unlocked = true;
      } catch {
        unlocked = false;
      }
    }
    if (!unlocked) {
      const AudioCtor = audioContextConstructor();
      if (AudioCtor) {
        try {
          const context = new AudioCtor();
          await context.resume();
          await context.close();
          unlocked = true;
        } catch {
          unlocked = false;
        }
      }
    }
    if (unlocked && pending) play(pending);
    return unlocked;
  };

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    generation += 1;
    pending = null;
    const active = controller;
    controller = null;
    if (active) {
      try {
        active.abort();
      } catch {
        /* Ignore. */
      }
    }
    clearAudio();
    setState("idle");
  };

  return {
    play,
    stop,
    unlock,
    dispose,
    getState: () => state,
    isBusy: () => state === "loading" || state === "playing" || state === "blocked",
  };
}