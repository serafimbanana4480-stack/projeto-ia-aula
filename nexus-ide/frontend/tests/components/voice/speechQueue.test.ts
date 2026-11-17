import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSpeechQueue, splitSpeechText } from "../../../lib/voice/speechQueue";
import { FakeAudio, deferred, installAudio, installObjectUrls } from "./fixtures";

/**
 * These tests exercise the real `speechQueue` module against controlled fakes.
 * `MediaRecorder`/microphone capture is not involved here; this file proves the
 * playback/cancellation contract only. Real speaker output must be verified in
 * a browser.
 */
describe("speechQueue", () => {
  let urls: { restore: () => void };

  beforeEach(() => {
    FakeAudio.reset();
    installAudio();
    urls = installObjectUrls();
  });

  afterEach(() => {
    urls.restore();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("reproduz os fragmentos por ordem e revoga cada URL", async () => {
    const fetchAudio = vi.fn(async (text: string) => new Blob([text], { type: "audio/wav" }));
    const queue = createSpeechQueue({ fetchAudio, chunkSize: 10 });

    queue.play({ text: "um dois tres", speed: 1 });
    expect(splitSpeechText("um dois tres", 10)).toEqual(["um dois", "tres"]);

    await vi.waitFor(() => expect(fetchAudio).toHaveBeenCalledTimes(1));
    const first = FakeAudio.instances.at(-1);
    expect(first).toBeTruthy();
    expect(first?.paused).toBe(false);

    first?.finish();
    await vi.waitFor(() => expect(fetchAudio).toHaveBeenCalledTimes(2));
    const second = FakeAudio.instances.at(-1);
    expect(second).toBeTruthy();

    second?.finish();
    await vi.waitFor(() => expect(queue.getState()).toBe("idle"));
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it("para a reprodução: aborta o fetch, pausa/limpa o áudio e revoga a URL", async () => {
    const fetchAudio = vi.fn(async () => new Blob(["a"], { type: "audio/wav" }));
    const queue = createSpeechQueue({ fetchAudio });

    queue.play({ text: "Olá", speed: 1 });
    await vi.waitFor(() => expect(FakeAudio.instances.length).toBe(1));
    const audio = FakeAudio.instances[0];
    expect(audio.paused).toBe(false);

    queue.stop();

    await vi.waitFor(() => expect(audio.paused).toBe(true));
    expect(audio.pauseCalls).toBeGreaterThan(0);
    expect(audio.src).toBe("");
    expect(URL.revokeObjectURL).toHaveBeenCalled();
    expect(queue.getState()).toBe("idle");
  });

  it("descarta um fragmento que chega depois de parar", async () => {
    const late = deferred<Blob>();
    const signals: AbortSignal[] = [];
    const fetchAudio = vi.fn((_text: string, { signal }: { signal: AbortSignal }) => {
      signals.push(signal);
      return late.promise;
    });
    const queue = createSpeechQueue({ fetchAudio });

    queue.play({ text: "Olá", speed: 1 });
    await vi.waitFor(() => expect(fetchAudio).toHaveBeenCalledTimes(1));
    expect(queue.getState()).toBe("loading");

    queue.stop();
    expect(signals[0].aborted).toBe(true);

    late.resolve(new Blob(["atrasado"], { type: "audio/wav" }));
    await Promise.resolve();
    await Promise.resolve();

    expect(FakeAudio.instances.length).toBe(0);
    expect(queue.getState()).toBe("idle");
  });

  it("reporta bloqueio de autoplay e volta a tentar depois do desbloqueio", async () => {
    const fetchAudio = vi.fn(async () => new Blob(["a"], { type: "audio/wav" }));
    let created = 0;
    const queue = createSpeechQueue({
      fetchAudio,
      createAudioElement: (url) => {
        created += 1;
        if (created === 1) FakeAudio.nextPlayError = { name: "NotAllowedError" };
        return new FakeAudio(url) as unknown as HTMLAudioElement;
      },
    });

    queue.play({ text: "Olá", speed: 1 });
    await vi.waitFor(() => expect(queue.getState()).toBe("blocked"));

    await expect(queue.unlock()).resolves.toBe(true);
    await vi.waitFor(() => expect(queue.getState()).toBe("playing"));
    FakeAudio.instances.at(-1)?.finish();
    await vi.waitFor(() => expect(queue.getState()).toBe("idle"));
  });

  it("não reproduz em duplicado quando um novo turno começa", async () => {
    const gates: ReturnType<typeof deferred<Blob>>[] = [];
    const fetchAudio = vi.fn(() => {
      const gate = deferred<Blob>();
      gates.push(gate);
      return gate.promise;
    });
    const queue = createSpeechQueue({ fetchAudio });

    queue.play({ text: "primeiro", speed: 1 });
    queue.play({ text: "segundo", speed: 1 });

    await vi.waitFor(() => expect(fetchAudio).toHaveBeenCalledTimes(2));
    gates[1].resolve(new Blob(["2"], { type: "audio/wav" }));
    await vi.waitFor(() => expect(FakeAudio.instances.length).toBe(1));

    // The superseded first request resolves late and must not play.
    gates[0].resolve(new Blob(["1"], { type: "audio/wav" }));
    await Promise.resolve();
    await Promise.resolve();

    expect(FakeAudio.instances.length).toBe(1);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("descarta reprodução depois de dispose e não volta a reproduzir", async () => {
    const fetchAudio = vi.fn(async () => new Blob(["a"], { type: "audio/wav" }));
    const queue = createSpeechQueue({ fetchAudio });

    queue.dispose();
    queue.play({ text: "Olá", speed: 1 });
    expect(fetchAudio).not.toHaveBeenCalled();
    expect(queue.getState()).toBe("idle");
  });
});