import { vi } from "vitest";

/**
 * Controlled browser fakes for the voice tests.
 *
 * These are *mocks*: they replace `MediaRecorder`, `Audio` and the media
 * streams with deterministic objects so the component's state machine can be
 * exercised in jsdom. They are not a real browser and do not prove that a
 * microphone or speaker works; only a real-browser run can do that.
 */

type Listener = () => void;

export class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];

  static isTypeSupported(type: string): boolean {
    return type === "audio/webm" || type === "audio/webm;codecs=opus" || type === "audio/mp4";
  }

  state: "inactive" | "recording" = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;

  constructor(
    public stream: MediaStream,
    public options?: { mimeType?: string },
  ) {
    FakeMediaRecorder.instances.push(this);
  }

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    if (this.state !== "recording") return;
    this.state = "inactive";
    this.ondataavailable?.({
      data: new Blob(["voice"], { type: this.options?.mimeType ?? "audio/webm" }),
    });
    this.onstop?.();
  }

  emitError(): void {
    this.onerror?.(new Error("recorder failed"));
  }

  static reset(): void {
    FakeMediaRecorder.instances = [];
  }
}

export class FakeAudio {
  static instances: FakeAudio[] = [];
  static nextPlayError: unknown = null;

  src = "";
  muted = false;
  paused = true;
  playCalls = 0;
  pauseCalls = 0;
  loadCalls = 0;
  private listeners = new Map<string, Set<Listener>>();

  constructor(public url: string) {
    FakeAudio.instances.push(this);
  }

  play(): Promise<void> {
    this.playCalls += 1;
    if (FakeAudio.nextPlayError) {
      const error = FakeAudio.nextPlayError;
      FakeAudio.nextPlayError = null;
      return Promise.reject(error);
    }
    this.paused = false;
    return Promise.resolve();
  }

  pause(): void {
    this.pauseCalls += 1;
    this.paused = true;
  }

  removeAttribute(name: string): void {
    if (name === "src") this.src = "";
  }

  load(): void {
    this.loadCalls += 1;
  }

  addEventListener(type: string, listener: Listener): void {
    const set = this.listeners.get(type) ?? new Set<Listener>();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }

  emit(type: string): void {
    for (const listener of [...(this.listeners.get(type) ?? [])]) listener();
  }

  finish(): void {
    this.emit("ended");
  }

  static reset(): void {
    FakeAudio.instances = [];
    FakeAudio.nextPlayError = null;
  }
}

export interface FakeTrack {
  stop: ReturnType<typeof vi.fn>;
  onended: (() => void) | null;
  kind: string;
  readyState: string;
}

export interface FakeStream {
  stream: MediaStream;
  track: FakeTrack;
  stop: ReturnType<typeof vi.fn>;
}

export function makeStream(): FakeStream {
  const stop = vi.fn();
  const track: FakeTrack = { stop, onended: null, kind: "audio", readyState: "live" };
  const stream = {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  } as unknown as MediaStream;
  return { stream, track, stop };
}

export interface MediaEnvironment {
  getUserMedia: ReturnType<typeof vi.fn>;
  enumerateDevices: ReturnType<typeof vi.fn>;
  restore: () => void;
}

export function installMedia(options?: {
  tracks?: FakeTrack[];
  devices?: MediaDeviceInfo[];
}): MediaEnvironment {
  const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
  const tracks = options?.tracks ?? [makeStream().track];
  const getUserMedia = vi.fn(async () => ({
    getTracks: () => tracks,
    getAudioTracks: () => tracks,
  }) as unknown as MediaStream);
  const enumerateDevices = vi.fn(async () => options?.devices ?? []);

  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia, enumerateDevices },
  });

  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);

  return {
    getUserMedia,
    enumerateDevices,
    restore: () => {
      if (originalMediaDevices) Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
      else Reflect.deleteProperty(navigator, "mediaDevices");
      vi.unstubAllGlobals();
    },
  };
}

export function installAudio(): void {
  vi.stubGlobal("Audio", FakeAudio);
}

export function installObjectUrls(): { restore: () => void } {
  const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
  const originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
  let counter = 0;
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: vi.fn(() => `blob:voice-${++counter}`),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
  return {
    restore: () => {
      if (originalCreate) Object.defineProperty(URL, "createObjectURL", originalCreate);
      else Reflect.deleteProperty(URL, "createObjectURL");
      if (originalRevoke) Object.defineProperty(URL, "revokeObjectURL", originalRevoke);
      else Reflect.deleteProperty(URL, "revokeObjectURL");
    },
  };
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}