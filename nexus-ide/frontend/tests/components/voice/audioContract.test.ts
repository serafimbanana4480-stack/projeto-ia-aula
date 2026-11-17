import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_AUDIO_BYTES,
  MAX_RECORDING_MS,
  baseMimeType,
  formatElapsed,
  pickAudioMimeType,
  releaseStream,
  supportsCapture,
} from "../../../lib/voice/audio";
import { describeMicrophoneError } from "../../../lib/voice/errors";

describe("voice audio contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, "mediaDevices");
  });

  it("limita a gravação ao contrato do backend", () => {
    expect(MAX_RECORDING_MS).toBe(59_000);
    expect(MAX_AUDIO_BYTES).toBe(10 * 1024 * 1024);
  });

  it("escolhe o primeiro content-type suportado pelo browser", () => {
    vi.stubGlobal("MediaRecorder", { isTypeSupported: (type: string) => type === "audio/mp4" });
    expect(pickAudioMimeType()).toBe("audio/mp4");

    vi.stubGlobal("MediaRecorder", { isTypeSupported: () => false });
    expect(pickAudioMimeType()).toBeNull();
  });

  it("normaliza o content-type para o backend", () => {
    expect(baseMimeType("audio/webm;codecs=opus")).toBe("audio/webm");
    expect(baseMimeType("AUDIO/MP4")).toBe("audio/mp4");
  });

  it("formata o tempo decorrido", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(5_000)).toBe("0:05");
    expect(formatElapsed(61_000)).toBe("1:01");
  });

  it("liberta todas as tracks e remove o handler de fim", () => {
    const first = { stop: vi.fn(), onended: vi.fn() };
    const second = { stop: vi.fn(), onended: vi.fn() };
    const stream = { getTracks: () => [first, second] } as unknown as MediaStream;

    releaseStream(stream);

    expect(first.stop).toHaveBeenCalledTimes(1);
    expect(second.stop).toHaveBeenCalledTimes(1);
    expect(first.onended).toBeNull();
    expect(second.onended).toBeNull();
  });

  it("reconhece captura indisponível", () => {
    Reflect.deleteProperty(navigator, "mediaDevices");
    expect(supportsCapture()).toBe(false);

    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: () => undefined },
    });
    expect(supportsCapture()).toBe(false);
  });

  it("traduz erros de permissão em ações concretas", () => {
    const withName = (name: string) => Object.assign(new Error("x"), { name });

    expect(describeMicrophoneError(withName("NotAllowedError")).kind).toBe("denied");
    expect(describeMicrophoneError(withName("NotFoundError")).kind).toBe("not-found");
    expect(describeMicrophoneError(withName("OverconstrainedError")).kind).toBe("not-found");
    expect(describeMicrophoneError(withName("NotReadableError")).kind).toBe("in-use");

    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: {} });
    const unknown = describeMicrophoneError(new Error("boom"));
    expect(unknown.kind).toBe("unknown");
    expect(unknown.message).toContain("boom");
  });
});