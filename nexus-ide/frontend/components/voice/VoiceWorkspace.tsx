"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AudioLines,
  CheckCircle2,
  Loader2,
  Mic,
  MicOff,
  PhoneOff,
  RefreshCw,
  Send,
  Settings2,
  Square,
  Volume2,
  VolumeX,
} from "lucide-react";
import AgentTranscript from "../chat/AgentTranscript";
import { apiUrl, getProviderModels, type AvailableModel } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useChatSessionsStore } from "../../hooks/useChatSessions";
import {
  MAX_AUDIO_BYTES,
  MAX_RECORDING_MS,
  baseMimeType,
  formatElapsed,
  pickAudioMimeType,
  releaseStream,
  supportsCapture,
} from "../../lib/voice/audio";
import { MICROPHONE_ERROR_MESSAGES, describeMicrophoneError } from "../../lib/voice/errors";
import { responseError } from "../../lib/voice/http";
import { newTurnId, newVoiceSessionId } from "../../lib/voice/ids";
import { createSpeechQueue, type SpeechState } from "../../lib/voice/speechQueue";
import styles from "./VoiceWorkspace.module.css";

type VoiceStatus = {
  stt: { ready: boolean; engine: string; models: { id: string; installed: boolean }[]; devices: string[]; default_model?: string };
  tts: { ready: boolean; engine: string; voices: { id: string; name: string; language: string }[]; accent_note: string };
};

type Turn = { id: string; text: string; start: number };

type VoicePhase =
  | "idle"
  | "requesting"
  | "recording"
  | "transcribing"
  | "processing"
  | "speaking"
  | "interrupted"
  | "error";

type MicState = "unknown" | "granted" | "denied" | "unavailable";

const PHASE_LABEL: Record<VoicePhase, string> = {
  idle: "Pronto",
  requesting: "A pedir acesso ao microfone",
  recording: "A ouvir",
  transcribing: "A transcrever",
  processing: "A trabalhar",
  speaking: "A falar",
  interrupted: "Interrompido",
  error: "Erro",
};

const PHASE_DESCRIPTION: Record<VoicePhase, string> = {
  idle: "O microfone só é aberto quando o ativas. A sessão é por turnos.",
  requesting: "A pedir permissão para o microfone. Aceita o pedido do browser.",
  recording: "Microfone ativo. Carrega novamente para terminar e transcrever.",
  transcribing: "A converter a tua fala em texto. Só a transcrição final segue para o modelo.",
  processing: "A preparar a resposta. O microfone está fechado.",
  speaking: "A reproduzir a resposta. Podes parar a voz sem cancelar a resposta.",
  interrupted: "A captura foi interrompida. Podes tentar novamente.",
  error: "Ocorreu um erro recuperável. Tenta novamente ou revê o diagnóstico.",
};

function isEmbeddingModel(model: AvailableModel): boolean {
  // Names and explicit embedding-only metadata are evidence; absence of chat
  // capabilities alone is not, since many local catalogs omit capabilities.
  const name = `${model.id} ${model.name ?? ""}`;
  const namedEmbedding = /(?:^|[\s-_./:])embed(?:ding)?s?(?=$|[\s-_./:])/i.test(name);
  const caps = model.capabilities ?? [];
  return namedEmbedding || (caps.length > 0 && caps.every((cap) => /^(?:embed|embedding|embeddings)$/i.test(cap)));
}

function tokenText(events: { type: string; content?: string }[]): string {
  return events.filter((event) => event.type === "token").map((event) => event.content ?? "").join("");
}

/** Real microphone level, when the browser exposes the Web Audio API. */
function useInputLevel(stream: MediaStream | null, active: boolean): number {
  const [level, setLevel] = useState(0);

  useEffect(() => {
    if (!active || !stream || typeof window === "undefined") {
      setLevel(0);
      return;
    }
    const AudioCtor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (typeof AudioCtor !== "function") {
      setLevel(0);
      return;
    }

    let context: AudioContext;
    try {
      context = new AudioCtor();
    } catch {
      setLevel(0);
      return;
    }

    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    let frame = 0;
    let lastPaint = 0;
    let lastLevel = 0;

    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let index = 0; index < data.length; index += 1) {
        const value = (data[index] - 128) / 128;
        sum += value * value;
      }
      const next = Math.min(1, Math.sqrt(sum / data.length) * 3.2);
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      // Throttle repaints: the meter is decorative, not a 60 fps render loop.
      if (now - lastPaint > 70 || Math.abs(next - lastLevel) > 0.08) {
        lastPaint = now;
        lastLevel = next;
        setLevel(next);
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);

    return () => {
      window.cancelAnimationFrame(frame);
      source.disconnect();
      analyser.disconnect();
      void context.close().catch(() => {});
    };
  }, [stream, active]);

  return level;
}

function LevelBars({ level, active }: { level: number; active: boolean }) {
  return (
    <div className={styles.levelMeter} aria-hidden="true">
      {[0, 1, 2, 3, 4].map((index) => {
        const lit = active && level >= (index + 1) * 0.14;
        return <span key={index} className={lit ? styles.levelOn : undefined} style={{ height: `${7 + index * 3}px` }} />;
      })}
    </div>
  );
}

/** Isolates the analyser repaint so the rest of the workspace does not re-render at meter rate. */
function LiveLevelBars({ stream, active }: { stream: MediaStream | null; active: boolean }) {
  const level = useInputLevel(stream, active);
  return <LevelBars level={level} active={active} />;
}

export default function VoiceWorkspace() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [models, setModels] = useState<AvailableModel[]>([]);
  const [modelError, setModelError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [sttModel, setSttModel] = useState("");
  const [device, setDevice] = useState("cpu");
  const [voice, setVoice] = useState("");
  const [speed, setSpeed] = useState(1);
  const [speak, setSpeak] = useState(true);
  const [handsFree, setHandsFree] = useState(false);
  const [muted, setMuted] = useState(false);
  const [inputDevices, setInputDevices] = useState<MediaDeviceInfo[]>([]);
  const [inputDevice, setInputDevice] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [voiceSessionId, setVoiceSessionId] = useState("");
  const [starting, setStarting] = useState(false);
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [speechState, setSpeechState] = useState<SpeechState>("idle");
  const [micState, setMicState] = useState<MicState>("unknown");
  const [captureMime, setCaptureMime] = useState("");
  const [captureStream, setCaptureStream] = useState<MediaStream | null>(null);
  const [currentAudioId, setCurrentAudioId] = useState("");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [preferencesReady, setPreferencesReady] = useState(false);

  const recorder = useRef<MediaRecorder | null>(null);
  const media = useRef<MediaStream | null>(null);
  const chunks = useRef<BlobPart[]>([]);
  const captureTimer = useRef<number | null>(null);
  const elapsedTimer = useRef<number | null>(null);
  const startedAt = useRef<number | null>(null);
  const epoch = useRef(0);
  const captureBusy = useRef(false);
  const transcribeController = useRef<AbortController | null>(null);
  const sending = useRef(false);
  const wasStreaming = useRef(false);
  const cancelled = useRef(false);
  const autoSpoken = useRef<Set<string>>(new Set());
  const handsFreeArmed = useRef(false);

  const createSession = useChatSessionsStore((state) => state.create);
  const { events, streaming, busyOtherSession, error: streamError, send, cancel } = useAgentStream(sessionId);

  const current = useMemo(
    () => models.find((model) => `${model.provider}:${model.id}` === selectedModel),
    [models, selectedModel],
  );
  const parts = useMemo(
    () => turns.map((turn, index) => events.slice(turn.start, turns[index + 1]?.start)),
    [turns, events],
  );

  // ── preferences ──────────────────────────────────────────────────────────
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("nexus.voice.preferences") ?? "{}") as Record<string, unknown>;
      if (saved.modelConfirmed === true && typeof saved.model === "string") setSelectedModel(saved.model);
      if (typeof saved.sttModel === "string") setSttModel(saved.sttModel);
      if (typeof saved.device === "string") setDevice(saved.device);
      if (typeof saved.voice === "string") setVoice(saved.voice);
      if (typeof saved.speed === "number" && saved.speed >= 0.7 && saved.speed <= 1.3) setSpeed(saved.speed);
      if (typeof saved.speak === "boolean") setSpeak(saved.speak);
      if (typeof saved.handsFree === "boolean") setHandsFree(saved.handsFree);
      if (typeof saved.inputDevice === "string") setInputDevice(saved.inputDevice);
    } catch {
      /* Unavailable or corrupt storage must not prevent use. */
    }
    setPreferencesReady(true);
  }, []);

  useEffect(() => {
    if (!preferencesReady) return;
    try {
      localStorage.setItem(
        "nexus.voice.preferences",
        JSON.stringify({ model: selectedModel, modelConfirmed: Boolean(selectedModel), sttModel, device, voice, speed, speak, handsFree, inputDevice }),
      );
    } catch {
      /* Optional preferences. */
    }
  }, [preferencesReady, selectedModel, sttModel, device, voice, speed, speak, handsFree, inputDevice]);

  // ── speech queue (one instance for the component lifetime) ─────────────────
  const queue = useMemo(
    () =>
      createSpeechQueue({
        fetchAudio: async (text, { voice: requestedVoice, speed: requestedSpeed, signal }) => {
          try {
            const response = await authenticatedFetch(apiUrl("/api/voice/synthesize"), {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              signal,
              body: JSON.stringify({ text, voice: requestedVoice || undefined, speed: requestedSpeed }),
            });
            if (!response.ok) throw new Error(await responseError(response));
            return await response.blob();
          } catch (reason) {
            // `authenticatedFetch` wraps transport errors in ApiError; re-expose
            // an abort so the playback queue can treat it as cancellation.
            if (signal.aborted) throw new DOMException("Aborted", "AbortError");
            throw reason;
          }
        },
        onState: (next, detail) => {
          setSpeechState(next);
          if (next === "error") setSpeechError(detail ?? "A síntese de voz falhou.");
          if (next === "blocked") setSpeechError("O browser bloqueou a reprodução. Usa “Ativar áudio”.");
          if (next === "loading" || next === "playing") setSpeechError(null);
          if (next === "idle") setPhase((currentPhase) => (currentPhase === "speaking" ? "idle" : currentPhase));
        },
      }),
    [],
  );

  useEffect(() => () => queue.dispose(), [queue]);

  // ── backend status ─────────────────────────────────────────────────────────
  const refresh = useCallback(async () => {
    setStatusError(null);
    setModelError(null);
    const [statusResult, ...modelResults] = await Promise.allSettled([
      authenticatedFetch(apiUrl("/api/voice/status")).then(async (response) => {
        if (!response.ok) throw new Error(await responseError(response));
        return (await response.json()) as VoiceStatus;
      }),
      getProviderModels("ollama", true),
      getProviderModels("lmstudio", true),
    ]);
    if (statusResult.status === "fulfilled") setStatus(statusResult.value);
    else {
      setStatus(null);
      setStatusError("Não foi possível consultar os motores de voz. Confirma que o backend está ligado.");
    }
    const found = modelResults.flatMap((result) =>
      result.status === "fulfilled" && !result.value.error
        ? result.value.models.filter((model) => !isEmbeddingModel(model))
        : [],
    );
    const uniqueModels = [...new Map(found.map((model) => [`${model.provider}:${model.id}`, model])).values()];
    setModels(uniqueModels);
    if (!uniqueModels.length) {
      setModelError("Não encontrei modelos locais disponíveis. Inicia o Ollama ou o LM Studio e carrega um modelo.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!status) return;
    setSttModel((old) =>
      status.stt.models.some((model) => model.id === old && model.installed)
        ? old
        : status.stt.models.find((model) => model.id === status.stt.default_model && model.installed)?.id ??
          status.stt.models.find((model) => model.installed)?.id ??
          "",
    );
    setVoice((old) => (status.tts.voices.some((entry) => entry.id === old) ? old : status.tts.voices[0]?.id ?? ""));
    setDevice((old) => (status.stt.devices.includes(old) ? old : status.stt.devices[0] ?? "cpu"));
  }, [status]);

  // ── device inventory ───────────────────────────────────────────────────────
  const refreshInputDevices = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = (await navigator.mediaDevices.enumerateDevices()).filter((entry) => entry.kind === "audioinput");
      setInputDevices(devices);
      setInputDevice((old) => (old && devices.some((entry) => entry.deviceId === old) ? old : ""));
    } catch {
      /* Enumeration is best-effort. */
    }
  }, []);

  useEffect(() => {
    const mediaDevices = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!mediaDevices || typeof mediaDevices.addEventListener !== "function") return;
    const onChange = () => void refreshInputDevices();
    mediaDevices.addEventListener("devicechange", onChange);
    return () => mediaDevices.removeEventListener("devicechange", onChange);
  }, [refreshInputDevices]);

  // ── capture timers / teardown ──────────────────────────────────────────────
  const clearCaptureTimers = useCallback(() => {
    if (captureTimer.current !== null) {
      window.clearTimeout(captureTimer.current);
      captureTimer.current = null;
    }
    if (elapsedTimer.current !== null) {
      window.clearInterval(elapsedTimer.current);
      elapsedTimer.current = null;
    }
  }, []);

  const stopSpeech = useCallback(() => {
    queue.stop();
    setSpeechError(null);
    setPhase((currentPhase) => (currentPhase === "speaking" ? "idle" : currentPhase));
  }, [queue]);

  const transcribeBlob = useCallback(
    async (blob: Blob, captureEpoch: number) => {
      setPhase("transcribing");
      const controller = new AbortController();
      transcribeController.current = controller;
      try {
        const query = new URLSearchParams({ model: sttModel, device });
        const response = await authenticatedFetch(apiUrl(`/api/voice/transcribe?${query}`), {
          method: "POST",
          headers: { "Content-Type": blob.type || "audio/webm" },
          body: blob,
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(await responseError(response));
        const result = (await response.json()) as { text?: string };
        if (captureEpoch !== epoch.current) return; // A newer capture superseded this one.
        const text = (result.text ?? "").trim();
        if (text) {
          setInput(text);
          setNotice(null);
          setError(null);
        } else {
          setError("Não detetei fala. Tenta outra vez mais perto do microfone.");
        }
        setPhase("idle");
      } catch (reason) {
        if (controller.signal.aborted || captureEpoch !== epoch.current) return;
        setError(reason instanceof Error ? reason.message : "A transcrição falhou.");
        setPhase("error");
      } finally {
        if (transcribeController.current === controller) transcribeController.current = null;
      }
    },
    [sttModel, device],
  );

  const handleRecorderStop = useCallback(
    (captureEpoch: number, mime: string) => {
      const stream = media.current;
      releaseStream(stream);
      media.current = null;
      setCaptureStream(null);
      recorder.current = null;
      clearCaptureTimers();
      startedAt.current = null;
      setElapsedMs(0);
      captureBusy.current = false;

      if (captureEpoch !== epoch.current) {
        chunks.current = [];
        return;
      }
      const recorded = chunks.current;
      chunks.current = [];
      const blob = new Blob(recorded, { type: baseMimeType(mime) });
      if (!blob.size) {
        setPhase("idle");
        setError("Áudio vazio. Tenta novamente.");
        return;
      }
      if (blob.size > MAX_AUDIO_BYTES) {
        setPhase("idle");
        setError("Áudio demasiado grande. Tenta novamente.");
        return;
      }
      void transcribeBlob(blob, captureEpoch);
    },
    [clearCaptureTimers, transcribeBlob],
  );

  const discardCapture = useCallback(() => {
    epoch.current += 1;
    if (transcribeController.current) {
      transcribeController.current.abort();
      transcribeController.current = null;
    }
    clearCaptureTimers();
    const activeRecorder = recorder.current;
    recorder.current = null;
    if (activeRecorder) {
      activeRecorder.onstop = null;
      try {
        if (activeRecorder.state === "recording") activeRecorder.stop();
      } catch {
        /* Ignore. */
      }
    }
    releaseStream(media.current);
    media.current = null;
    setCaptureStream(null);
    chunks.current = [];
    captureBusy.current = false;
    startedAt.current = null;
    setElapsedMs(0);
    setPhase((currentPhase) =>
      currentPhase === "recording" || currentPhase === "requesting" || currentPhase === "transcribing" ? "idle" : currentPhase,
    );
  }, [clearCaptureTimers]);

  const finishCapture = useCallback(() => {
    clearCaptureTimers();
    const activeRecorder = recorder.current;
    if (activeRecorder && activeRecorder.state === "recording") {
      try {
        activeRecorder.stop(); // handleRecorderStop releases tracks and transcribes.
        return;
      } catch {
        /* Fall through to release. */
      }
    }
    recorder.current = null;
    releaseStream(media.current);
    media.current = null;
    setCaptureStream(null);
    captureBusy.current = false;
    startedAt.current = null;
    setElapsedMs(0);
    setPhase((currentPhase) => (currentPhase === "recording" || currentPhase === "requesting" ? "idle" : currentPhase));
  }, [clearCaptureTimers]);

  const beginCapture = useCallback(async () => {
    if (!sessionId || captureBusy.current) return;
    if (recorder.current?.state === "recording") return;
    if (!supportsCapture()) {
      setError(MICROPHONE_ERROR_MESSAGES.unsupported);
      setPhase("error");
      return;
    }
    if (muted) {
      setNotice("O microfone está silenciado. Ativa o microfone para falar.");
      return;
    }

    captureBusy.current = true;
    stopSpeech();
    setError(null);
    setNotice(null);
    setSpeechError(null);
    setPhase("requesting");

    const captureEpoch = ++epoch.current;
    releaseStream(media.current);
    media.current = null;
    setCaptureStream(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: inputDevice ? { deviceId: { exact: inputDevice } } : true,
      });
      if (captureEpoch !== epoch.current) {
        releaseStream(stream);
        captureBusy.current = false;
        return;
      }
      media.current = stream;
      setCaptureStream(stream);
      setMicState("granted");
      void refreshInputDevices();

      const [track] = typeof stream.getAudioTracks === "function" ? stream.getAudioTracks() : [];
      if (track) {
        track.onended = () => {
          if (captureEpoch !== epoch.current) return;
          setNotice("O microfone foi desligado ou perdeu-se. A gravação foi interrompida.");
          discardCapture();
          setPhase("interrupted");
        };
      }

      const mime = pickAudioMimeType();
      if (!mime || typeof MediaRecorder === "undefined") throw new Error(MICROPHONE_ERROR_MESSAGES.unsupported);

      const activeRecorder = new MediaRecorder(stream, { mimeType: mime });
      setCaptureMime(mime);
      chunks.current = [];
      activeRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunks.current.push(event.data);
      };
      activeRecorder.onstop = () => handleRecorderStop(captureEpoch, mime);
      recorder.current = activeRecorder;
      activeRecorder.start();
      captureBusy.current = false;
      setPhase("recording");
      startedAt.current = Date.now();
      setElapsedMs(0);
      elapsedTimer.current = window.setInterval(() => {
        if (startedAt.current !== null) setElapsedMs(Date.now() - startedAt.current);
      }, 250);
      captureTimer.current = window.setTimeout(() => finishCapture(), MAX_RECORDING_MS);
    } catch (reason) {
      if (captureEpoch !== epoch.current) return;
      releaseStream(media.current);
      media.current = null;
      setCaptureStream(null);
      recorder.current = null;
      captureBusy.current = false;
      clearCaptureTimers();
      startedAt.current = null;
      setElapsedMs(0);
      const described = describeMicrophoneError(reason);
      const kind: MicState = described.kind === "denied" ? "denied" : "unavailable";
      setMicState(kind);
      setError(described.message);
      setPhase("error");
    }
  }, [sessionId, muted, inputDevice, stopSpeech, refreshInputDevices, handleRecorderStop, discardCapture, finishCapture, clearCaptureTimers]);

  // ── playback ───────────────────────────────────────────────────────────────
  const speakTurn = useCallback(
    (turnId: string, text: string) => {
      const clean = text.trim();
      if (!clean) return;
      if (!status?.tts.ready) {
        setPhase((currentPhase) => (currentPhase === "speaking" || currentPhase === "processing" ? "idle" : currentPhase));
        return;
      }
      if (recorder.current?.state === "recording") discardCapture();
      setSpeechError(null);
      setPhase("speaking");
      const audioId = `audio-${turnId}`;
      setCurrentAudioId(audioId);
      queue.play({ text: clean, voice: voice || undefined, speed, audioId });
    },
    [queue, status, voice, speed, discardCapture],
  );

  useEffect(() => {
    const was = wasStreaming.current;
    wasStreaming.current = streaming;
    if (!was || streaming) return;
    if (cancelled.current) {
      cancelled.current = false;
      setPhase((currentPhase) => (currentPhase === "processing" ? "idle" : currentPhase));
      return;
    }
    if (streamError) {
      setPhase((currentPhase) => (currentPhase === "processing" ? "error" : currentPhase));
      return;
    }
    const last = turns[turns.length - 1];
    const text = last ? tokenText(parts[parts.length - 1] ?? []) : "";
    if (speak && status?.tts.ready && last && text.trim() && !autoSpoken.current.has(last.id)) {
      autoSpoken.current.add(last.id);
      speakTurn(last.id, text);
      return;
    }
    setPhase((currentPhase) => (currentPhase === "processing" ? "idle" : currentPhase));
  }, [streaming, streamError, turns, parts, speak, status, speakTurn]);

  // Hands-free is controlled alternation, never full-duplex: the microphone
  // only reopens once the assistant has finished speaking and nothing is
  // streaming. It never captures the bot's own voice.
  useEffect(() => {
    if (!handsFree || !sessionId || muted) return;
    if (!handsFreeArmed.current) return;
    if (phase !== "idle" || streaming || speechState === "loading" || speechState === "playing") return;
    if (turns.length === 0) return;
    handsFreeArmed.current = false;
    void beginCapture();
  }, [handsFree, sessionId, muted, phase, streaming, speechState, turns.length, beginCapture]);

  // ── session / turn actions ─────────────────────────────────────────────────
  const startSession = useCallback(async () => {
    setStarting(true);
    setError(null);
    setNotice(null);
    const session = await createSession("NEXUS Voice", "chat");
    setStarting(false);
    if (!session) {
      setError("Não consegui criar a sessão. Verifica a ligação ao backend.");
      return;
    }
    autoSpoken.current.clear();
    cancelled.current = false;
    handsFreeArmed.current = false;
    setVoiceSessionId(newVoiceSessionId());
    setSessionId(session.id);
    setTurns([]);
    setInput("");
    setPhase("idle");
  }, [createSession]);

  const endSession = useCallback(() => {
    discardCapture();
    queue.stop();
    if (streaming) cancel();
    cancelled.current = false;
    handsFreeArmed.current = false;
    autoSpoken.current.clear();
    setSessionId("");
    setTurns([]);
    setInput("");
    setError(null);
    setSpeechError(null);
    setNotice("Sessão terminada. O microfone e o áudio foram libertados.");
    setPhase("idle");
  }, [discardCapture, queue, streaming, cancel]);

  const submitMessage = useCallback(
    async (raw?: string) => {
      const message = (raw ?? input).trim();
      if (!message || !sessionId || !current || streaming || sending.current) return;
      sending.current = true;
      cancelled.current = false;
      stopSpeech();
      setError(null);
      setNotice(null);
      setInput("");

      const turnId = newTurnId();
      const start = events.length;
      setTurns((previous) => [...previous, { id: turnId, text: message, start }]);
      setPhase("processing");

      let accepted = false;
      try {
        accepted = await send(message, "chat", current.id, "", undefined, undefined, current.provider, true, true);
      } finally {
        sending.current = false;
      }

      if (!accepted) {
        setTurns((previous) => previous.filter((turn) => turn.id !== turnId));
        setInput((existing) => existing || message);
        setPhase((currentPhase) => (currentPhase === "processing" ? "idle" : currentPhase));
        return;
      }
      if (handsFree) handsFreeArmed.current = true;
    },
    [input, sessionId, current, streaming, send, events.length, stopSpeech, handsFree],
  );

  const cancelResponse = useCallback(() => {
    cancelled.current = true;
    cancel();
    queue.stop();
    setSpeechError(null);
    setPhase("interrupted");
    setNotice("Resposta cancelada. O áudio foi interrompido.");
  }, [cancel, queue]);

  const toggleMuted = useCallback(() => {
    const next = !muted;
    setMuted(next);
    if (next) {
      discardCapture();
      setNotice("Microfone silenciado. O NEXUS não te consegue ouvir.");
    } else {
      setNotice(null);
    }
  }, [muted, discardCapture]);

  const toggleHandsFree = useCallback(() => {
    const next = !handsFree;
    setHandsFree(next);
    handsFreeArmed.current = next && Boolean(sessionId) && turns.length > 0;
    if (!next) discardCapture();
  }, [handsFree, sessionId, turns.length, discardCapture]);

  // ── unmount cleanup: tracks, timers, listeners, buffers, audio ─────────────
  useEffect(
    () => () => {
      epoch.current += 1;
      if (transcribeController.current) {
        transcribeController.current.abort();
        transcribeController.current = null;
      }
      clearCaptureTimers();
      const activeRecorder = recorder.current;
      recorder.current = null;
      if (activeRecorder) {
        activeRecorder.onstop = null;
        try {
          if (activeRecorder.state === "recording") activeRecorder.stop();
        } catch {
          /* Ignore. */
        }
      }
      releaseStream(media.current);
      media.current = null;
      chunks.current = [];
      startedAt.current = null;
    },
    [clearCaptureTimers],
  );

  // ── derived view state ─────────────────────────────────────────────────────
  const displayPhase: VoicePhase =
    phase === "idle" && streaming
      ? "processing"
      : phase === "idle" && (speechState === "loading" || speechState === "playing")
        ? "speaking"
        : phase;

  const captureBusyPhase =
    phase === "requesting" ||
    phase === "transcribing" ||
    phase === "processing" ||
    phase === "speaking" ||
    speechState === "loading" ||
    speechState === "playing";
  const micDisabled =
    !sessionId || muted || !status?.stt.ready || !sttModel || streaming || busyOtherSession || captureBusyPhase;
  const micLabel =
    phase === "recording"
      ? "Terminar gravação"
      : phase === "requesting"
        ? "A pedir microfone"
        : phase === "transcribing"
          ? "A transcrever"
          : "Gravar voz";
  const speaking = speechState === "loading" || speechState === "playing" || displayPhase === "speaking";
  const phaseLabel = muted && phase === "idle" ? "Microfone silenciado" : PHASE_LABEL[displayPhase];
  const statusDot = statusError ? "Sem ligação" : status ? "Backend ligado" : "A verificar";
  const lastTurnText = turns.length ? tokenText(parts[parts.length - 1] ?? []) : "";
  const micStateLabel: Record<MicState, string> = {
    unknown: "Por confirmar",
    granted: "Autorizado",
    denied: "Recusado",
    unavailable: "Indisponível",
  };

  const diagnostics: [string, string][] = [
    ["Sessão de voz", voiceSessionId || "—"],
    ["Sessão de conversa", sessionId || "—"],
    ["Estado", displayPhase],
    ["Microfone", micStateLabel[micState]],
    ["Formato de captura", captureMime || "—"],
    ["Reprodução de voz", speechState],
    ["Áudio atual", currentAudioId || "—"],
    ["Reconhecimento", status ? `${status.stt.engine} · ${sttModel || "sem modelo"}` : "—"],
    ["Síntese", status ? `${status.tts.engine} · ${voice || "sem voz"}` : "—"],
    ["Turnos", String(turns.length)],
    ["Último erro", error || speechError || "—"],
  ];

  return (
    <div className={styles.workspace}>
      <div className={styles.ambient} aria-hidden="true" />
      <div className={styles.content}>
        <header className={styles.header}>
          <div>
            <div className={styles.eyebrow}>
              <AudioLines size={14} /> NEXUS / VOICE
            </div>
            <h1>
              Uma conversa, <span>infinitas possibilidades.</span>
            </h1>
            <p>O teu espaço para falar com o NEXUS. Tu controlas quando o microfone está ligado.</p>
          </div>
          <button className={styles.refresh} onClick={() => void refresh()} aria-label="Atualizar estado">
            <RefreshCw size={16} /> Atualizar
          </button>
        </header>

        <div className={styles.grid}>
          <section className={`${styles.card} ${styles.stage}`} aria-label="Sessão de voz">
            <div className={styles.stageTop}>
              <span>
                <span className={styles.dot} /> {statusDot}
              </span>
              <span>PROCESSAMENTO LOCAL</span>
            </div>

            <div
              className={`${styles.orbWrap} ${phase === "recording" ? styles.listening : ""} ${
                displayPhase === "speaking" ? styles.speaking : ""
              } ${displayPhase === "error" || displayPhase === "interrupted" ? styles.alerting : ""}`}
              aria-hidden="true"
            >
              <div className={styles.orbit} />
              <div className={styles.orbitTwo} />
              <div className={styles.orb}>
                <AudioLines size={50} strokeWidth={1.1} />
              </div>
              <LiveLevelBars stream={captureStream} active={phase === "recording"} />
            </div>

            <div className={styles.stageText} aria-live="polite">
              <div className={styles.liveLabel} data-testid="voice-state">
                <span className={styles.dot} /> {phaseLabel}
              </div>
              <h2 data-testid="voice-headline">NEXUS</h2>
              <p>{displayPhase === "interrupted" && notice ? notice : PHASE_DESCRIPTION[displayPhase]}</p>
            </div>

            {phase === "recording" && (
              <div className={styles.recordingMeta}>
                <span>{formatElapsed(elapsedMs)}</span>
                <span>·</span>
                <span>máx. {formatElapsed(MAX_RECORDING_MS)}</span>
              </div>
            )}

            {input && !streaming && (
              <div className={styles.transcriptPreview} data-testid="voice-transcript">
                <span className={styles.transcriptLabel}>Transcrição final</span>
                <p>{input}</p>
                <button className={styles.ghost} onClick={() => setInput("")}>
                  Limpar
                </button>
              </div>
            )}

            {streaming && lastTurnText && (
              <div className={styles.transcriptPreview}>
                <span className={styles.transcriptLabel}>Resposta parcial</span>
                <p>{lastTurnText}</p>
              </div>
            )}

            <div className={styles.controls}>
              {!sessionId ? (
                <button className={styles.primary} onClick={() => void startSession()} disabled={starting}>
                  {starting ? <Loader2 className={styles.spinner} size={18} /> : <AudioLines size={18} />} Iniciar sessão
                </button>
              ) : (
                <>
                  <button
                    className={styles.micButton}
                    data-testid="voice-mic"
                    onClick={() => (phase === "recording" ? finishCapture() : void beginCapture())}
                    disabled={micDisabled}
                    aria-label={micLabel}
                    aria-pressed={phase === "recording"}
                  >
                    {phase === "requesting" || phase === "transcribing" ? (
                      <Loader2 className={styles.spinner} size={21} />
                    ) : phase === "recording" ? (
                      <MicOff size={21} />
                    ) : (
                      <Mic size={21} />
                    )}
                  </button>
                  {speaking && (
                    <button className={styles.secondary} data-testid="voice-stop-speech" onClick={stopSpeech}>
                      <VolumeX size={17} /> Parar voz
                    </button>
                  )}
                  {(streaming || displayPhase === "processing") && (
                    <button className={styles.danger} data-testid="voice-cancel-response" onClick={cancelResponse}>
                      <Square size={15} /> Cancelar resposta
                    </button>
                  )}
                  <button className={styles.secondary} data-testid="voice-hangup" onClick={endSession}>
                    <PhoneOff size={17} /> Terminar sessão
                  </button>
                  <button
                    className={styles.secondary}
                    aria-pressed={muted}
                    onClick={toggleMuted}
                    title={muted ? "Ativar microfone" : "Silenciar microfone"}
                  >
                    {muted ? <MicOff size={17} /> : <Mic size={17} />} {muted ? "Microfone silenciado" : "Silenciar"}
                  </button>
                </>
              )}
            </div>

            {speechState === "blocked" && (
              <div className={styles.unlockRow}>
                <button
                  className={styles.secondary}
                  data-testid="voice-speech-unlock"
                  onClick={() => {
                    void queue.unlock().then((ok) => {
                      if (!ok) setSpeechError("O browser não permitiu ativar o áudio. Verifica as definições do site.");
                    });
                  }}
                >
                  <Volume2 size={17} /> Ativar áudio
                </button>
                <span>{speechError ?? "O browser bloqueou a reprodução automática."}</span>
              </div>
            )}

            {error && (
              <p className={styles.error} role="alert" data-testid="voice-error">
                {error}
              </p>
            )}
            {notice && displayPhase !== "interrupted" && <p className={styles.notice}>{notice}</p>}
            {speechError && speechState !== "blocked" && (
              <p className={styles.notice} role="alert">
                {speechError}
              </p>
            )}
            {streamError && <p className={styles.error} role="alert">{streamError}</p>}

            <p className={styles.disclaimer}>
              A sessão de voz é por turnos (half-duplex). A gravação não fica guardada e só a transcrição final segue para o
              modelo.
            </p>
          </section>

          <aside className={styles.side}>
            <section className={styles.card}>
              <div className={styles.sectionHead}>
                <div>
                  <div className={styles.eyebrow}>DISPOSITIVOS LOCAIS</div>
                  <h2>Estado do sistema</h2>
                </div>
                <Activity size={19} />
              </div>
              <div className={styles.statusRow}>
                <span>Reconhecimento</span>
                <strong className={status?.stt.ready ? styles.good : styles.off}>
                  {status?.stt.ready ? "Disponível" : "Indisponível"}
                </strong>
              </div>
              <div className={styles.statusRow}>
                <span>Voz de resposta</span>
                <strong className={status?.tts.ready ? styles.good : styles.off}>
                  {status?.tts.ready ? "Disponível" : "Indisponível"}
                </strong>
              </div>
              <div className={styles.statusRow}>
                <span>Modelo de linguagem</span>
                <strong className={current ? styles.good : styles.off}>{current ? "Selecionado" : "Em falta"}</strong>
              </div>
              <div className={styles.statusRow}>
                <span>Microfone</span>
                <strong className={micState === "granted" ? styles.good : styles.off}>
                  {micStateLabel[micState]}
                </strong>
              </div>
              {statusError && (
                <p className={styles.notice} role="alert">
                  {statusError}
                </p>
              )}
              {modelError && <p className={styles.notice}>{modelError}</p>}
            </section>

            <section className={styles.card}>
              <div className={styles.sectionHead}>
                <div>
                  <div className={styles.eyebrow}>AJUSTA À TUA MEDIDA</div>
                  <h2>Configuração</h2>
                </div>
              </div>
              <label className={styles.label}>
                Modelo local
                <select value={current ? selectedModel : ""} onChange={(event) => setSelectedModel(event.target.value)} disabled={streaming}>
                  <option value="">Seleciona um modelo</option>
                  {models.map((model) => (
                    <option key={`${model.provider}:${model.id}`} value={`${model.provider}:${model.id}`}>
                      {model.provider} · {model.name || model.id}
                    </option>
                  ))}
                </select>
              </label>
              <p className={styles.hint}>
                Escolhe um modelo de conversa adequado à tua memória disponível. Alguns catálogos não indicam as capacidades;
                confirma que o modelo escolhido suporta conversa.
              </p>
              <label className={styles.label}>
                Reconhecimento
                <select value={sttModel} onChange={(event) => setSttModel(event.target.value)}>
                  <option value="">Sem modelo instalado</option>
                  {status?.stt.models
                    .filter((model) => model.installed)
                    .map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.id}
                      </option>
                    ))}
                </select>
              </label>
              <label className={styles.label}>
                Processamento
                <select value={device} onChange={(event) => setDevice(event.target.value)}>
                  {(status?.stt.devices ?? ["cpu"]).map((entry) => (
                    <option key={entry} value={entry}>
                      {entry.toUpperCase()}
                    </option>
                  ))}
                </select>
              </label>
              <label className={styles.label}>
                Voz
                <select value={voice} onChange={(event) => setVoice(event.target.value)}>
                  <option value="">Sem voz instalada</option>
                  {status?.tts.voices.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name} · {entry.language}
                    </option>
                  ))}
                </select>
              </label>
              {inputDevices.length > 0 && (
                <label className={styles.label}>
                  Microfone
                  <select value={inputDevice} onChange={(event) => setInputDevice(event.target.value)}>
                    <option value="">Predefinido</option>
                    {inputDevices.map((entry) => (
                      <option key={entry.deviceId} value={entry.deviceId}>
                        {entry.label || "Microfone"}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className={styles.label}>
                Velocidade da voz: {speed.toFixed(1)}×
                <input type="range" min="0.7" max="1.3" step="0.1" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} />
              </label>
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={speak}
                  onChange={(event) => {
                    setSpeak(event.target.checked);
                    if (!event.target.checked) stopSpeech();
                  }}
                />{" "}
                Responder por voz
              </label>
              <label className={styles.toggle}>
                <input type="checkbox" checked={handsFree} onChange={toggleHandsFree} /> Mãos-livres (alternância controlada)
              </label>
              <p className={styles.hint}>
                Em mãos-livres o microfone só abre quando é a tua vez e fecha enquanto o NEXUS fala. Não é full-duplex.
              </p>
              {status?.tts.accent_note && <p className={styles.hint}>{status.tts.accent_note}</p>}
            </section>

            <section className={styles.card}>
              <button className={styles.diagnosticToggle} onClick={() => setDiagnosticsOpen((open) => !open)} aria-expanded={diagnosticsOpen}>
                <Settings2 size={16} /> Diagnóstico
              </button>
              {diagnosticsOpen && (
                <dl className={styles.diagnostics} data-testid="voice-diagnostics">
                  {diagnostics.map(([label, value]) => (
                    <div key={label} className={styles.diagnosticRow}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                  <div className={styles.diagnosticRow}>
                    <dt>Gravação guardada</dt>
                    <dd>
                      <CheckCircle2 size={13} /> Não
                    </dd>
                  </div>
                </dl>
              )}
            </section>
          </aside>

          <section className={`${styles.card} ${styles.conversation}`} aria-label="Conversa">
            <div className={styles.sectionHead}>
              <div>
                <div className={styles.eyebrow}>A TUA CONVERSA</div>
                <h2>Conversar com o NEXUS</h2>
              </div>
              <Link href="/" className={styles.chatLink}>
                Abrir chat completo ↗
              </Link>
            </div>

            <div className={styles.messages} aria-live="polite">
              {!turns.length && (
                <div className={styles.empty}>
                  <AudioLines size={24} />
                  <p>Fala ou escreve. A transcrição aparece aqui para a reveres antes de enviar.</p>
                </div>
              )}
              {turns.map((turn, index) => (
                <div className={styles.turn} key={turn.id}>
                  <div className={styles.userMessage}>
                    <span>
                      Tu <em className={styles.badgeFinal}>final</em>
                    </span>
                    <p>{turn.text}</p>
                  </div>
                  <div className={styles.assistantMessage}>
                    <span>
                      NEXUS{" "}
                      {streaming && index === turns.length - 1 ? (
                        <em className={styles.badgePartial}>parcial</em>
                      ) : parts[index]?.length ? (
                        <em className={styles.badgeFinal}>final</em>
                      ) : null}
                    </span>
                    <AgentTranscript
                      events={parts[index] ?? []}
                      isStreaming={streaming && index === turns.length - 1}
                      renderMarkdown={(text) => <p className="whitespace-pre-wrap">{text}</p>}
                    />
                    {!streaming && parts[index]?.length > 0 && (
                      <button
                        className={styles.readButton}
                        onClick={() => speakTurn(turn.id, tokenText(parts[index] ?? []))}
                        disabled={!status?.tts.ready}
                      >
                        {speechState === "playing" ? <VolumeX size={14} /> : <Volume2 size={14} />} Ouvir resposta
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <form
              className={styles.composer}
              onSubmit={(event) => {
                event.preventDefault();
                void submitMessage();
              }}
            >
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder={sessionId ? "Escreve uma mensagem ou grava a tua voz…" : "Inicia uma sessão para conversar…"}
                aria-label="Mensagem para o NEXUS"
                disabled={!sessionId}
                rows={2}
              />
              <button
                type="submit"
                disabled={!sessionId || !current || !input.trim() || streaming || busyOtherSession || sending.current}
                aria-label="Enviar mensagem"
              >
                <Send size={19} />
              </button>
            </form>

            {busyOtherSession && (
              <div className={styles.runInfo}>Uma execução anterior ainda está ativa. Espera que termine antes de enviar outra mensagem.</div>
            )}
            {streaming && (
              <div className={styles.runInfo}>
                O NEXUS está a trabalhar. Podes parar a voz ou cancelar a resposta. Terminar a sessão mantém esta execução enquanto o
                painel estiver aberto; sair desta página pode cancelá-la.{" "}
                <button onClick={cancelResponse}>Cancelar tarefa</button>
              </div>
            )}
            <p className={styles.hint}>
              As ações que precisem de aprovação continuam a pedir a tua confirmação. Abrir o chat completo permite consultar o
              histórico guardado.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}