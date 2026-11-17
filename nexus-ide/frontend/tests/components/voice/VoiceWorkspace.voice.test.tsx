import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Component-level voice tests. `MediaRecorder`, `Audio`, `getUserMedia` and the
 * backend are controlled fakes; the state machine, cleanup and idempotency are
 * real. A real microphone/speaker still has to be exercised in a browser.
 */

const mocks = vi.hoisted(() => ({
  send: vi.fn(),
  create: vi.fn(),
  fetch: vi.fn(),
  models: vi.fn(),
  cancel: vi.fn(),
  stream: {
    events: [] as { type: string; content?: string }[],
    streaming: false,
    error: null as string | null,
    busyOtherSession: false,
  },
}));

vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path, getProviderModels: mocks.models }));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: mocks.fetch }));
vi.mock("../../../hooks/useAgentStream", () => ({
  useAgentStream: () => ({ ...mocks.stream, send: mocks.send, cancel: mocks.cancel }),
}));
vi.mock("../../../hooks/useChatSessions", () => ({
  useChatSessionsStore: (selector: (state: { create: typeof mocks.create }) => unknown) => selector({ create: mocks.create }),
}));
vi.mock("../../../components/chat/AgentTranscript", () => ({
  default: ({ events }: { events: { type: string; content?: string }[] }) => (
    <div data-testid="agent-transcript">{events.map((event, index) => <span key={index}>{event.content ?? ""}</span>)}</div>
  ),
}));

import VoiceWorkspace from "../../../components/voice/VoiceWorkspace";
import {
  FakeAudio,
  FakeMediaRecorder,
  deferred,
  installAudio,
  installMedia,
  installObjectUrls,
  makeStream,
  type MediaEnvironment,
} from "./fixtures";

const status = {
  stt: { ready: true, engine: "faster-whisper", models: [{ id: "base", installed: true }], devices: ["cpu"] },
  tts: { ready: true, engine: "piper", voices: [{ id: "pt", name: "Português", language: "pt-PT" }], accent_note: "Sotaque não verificado." },
};

const mediaEnvironments: MediaEnvironment[] = [];
let objectUrls: { restore: () => void } | null = null;

function addMedia(): MediaEnvironment {
  const environment = installMedia();
  mediaEnvironments.push(environment);
  return environment;
}

async function boot() {
  const utils = render(<VoiceWorkspace />);
  await screen.findByRole("option", { name: /ollama · Local/ });
  fireEvent.change(screen.getByLabelText("Modelo local"), { target: { value: "ollama:local-model" } });
  return utils;
}

async function startSession(): Promise<HTMLTextAreaElement> {
  fireEvent.click(screen.getByRole("button", { name: /Iniciar sessão/ }));
  const input = await screen.findByRole("textbox", { name: "Mensagem para o NEXUS" });
  await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
  return input as HTMLTextAreaElement;
}

describe("NEXUS Voice — captura, estados e idempotência", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    FakeAudio.reset();
    FakeMediaRecorder.reset();
    mocks.stream.events = [];
    mocks.stream.streaming = false;
    mocks.stream.error = null;
    mocks.stream.busyOtherSession = false;
    mocks.create.mockResolvedValue({ id: "voice-session" });
    mocks.send.mockResolvedValue(true);
    mocks.models.mockImplementation(async (provider: string) => ({
      error: null,
      models: provider === "ollama" ? [{ id: "local-model", name: "Local", provider: "ollama" }] : [],
    }));
    mocks.fetch.mockImplementation(async (url: string) => {
      if (url.includes("/voice/status")) return { ok: true, json: async () => status };
      if (url.includes("/voice/transcribe")) return { ok: true, json: async () => ({ text: "Texto reconhecido" }) };
      if (url.includes("/voice/synthesize")) return { ok: true, blob: async () => new Blob(["wav"], { type: "audio/wav" }) };
      return { ok: false, status: 500, json: async () => ({ detail: "erro" }) };
    });
    objectUrls = installObjectUrls();
  });

  afterEach(() => {
    while (mediaEnvironments.length) mediaEnvironments.pop()?.restore();
    objectUrls?.restore();
    objectUrls = null;
    FakeAudio.reset();
    vi.restoreAllMocks();
  });

  it("atualizar o estado não abre o microfone", async () => {
    const media = addMedia();
    await boot();
    await screen.findByText("Backend ligado");
    media.getUserMedia.mockClear();

    fireEvent.click(screen.getByRole("button", { name: /Atualizar/ }));
    await waitFor(() => expect(mocks.models).toHaveBeenCalledTimes(4));
    expect(media.getUserMedia).not.toHaveBeenCalled();
  });

  it("mostra um erro de permissão recuperável e volta a permitir tentar", async () => {
    const media = addMedia();
    media.getUserMedia.mockRejectedValueOnce(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
    await boot();
    await startSession();

    fireEvent.click(screen.getByRole("button", { name: "Gravar voz" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("O acesso ao microfone foi recusado");
    const mic = screen.getByTestId("voice-mic") as HTMLButtonElement;
    expect(mic.disabled).toBe(false);
  });

  it("percorre requesting → recording → transcribing → idle e mostra a transcrição final", async () => {
    const media = addMedia();
    const streamGate = deferred<MediaStream>();
    media.getUserMedia.mockReturnValueOnce(streamGate.promise);
    const transcribeGate = deferred<{ ok: boolean; json: () => Promise<{ text: string }> }>();
    mocks.fetch.mockImplementation(async (url: string) => {
      if (url.includes("/voice/status")) return { ok: true, json: async () => status };
      if (url.includes("/voice/transcribe")) return transcribeGate.promise;
      return { ok: false, status: 500, json: async () => ({ detail: "erro" }) };
    });

    await boot();
    const input = await startSession();

    fireEvent.click(screen.getByRole("button", { name: "Gravar voz" }));
    await waitFor(() => expect(screen.getByTestId("voice-state").textContent).toContain("A pedir acesso ao microfone"));

    streamGate.resolve(makeStream().stream);
    await waitFor(() => expect(screen.getByTestId("voice-state").textContent).toContain("A ouvir"));

    fireEvent.click(screen.getByRole("button", { name: "Terminar gravação" }));
    await waitFor(() => expect(screen.getByTestId("voice-state").textContent).toContain("A transcrever"));

    transcribeGate.resolve({ ok: true, json: async () => ({ text: "Texto reconhecido" }) });
    await waitFor(() => expect(input.value).toBe("Texto reconhecido"));
    await waitFor(() => expect(screen.getByTestId("voice-state").textContent).toContain("Pronto"));
  });

  it("liberta as tracks e o recorder ao terminar a sessão", async () => {
    addMedia();
    await boot();
    await startSession();

    fireEvent.click(screen.getByRole("button", { name: "Gravar voz" }));
    await screen.findByRole("button", { name: "Terminar gravação" });
    expect(FakeMediaRecorder.instances.length).toBe(1);
    expect(FakeMediaRecorder.instances[0].state).toBe("recording");

    const recorderStream = FakeMediaRecorder.instances[0].stream as unknown as {
      getTracks: () => { stop: ReturnType<typeof vi.fn> }[];
    };

    fireEvent.click(screen.getByRole("button", { name: "Terminar sessão" }));

    expect(recorderStream.getTracks()[0].stop).toHaveBeenCalled();
    expect(FakeMediaRecorder.instances[0].state).toBe("inactive");
    await waitFor(() => expect(screen.getByTestId("voice-state").textContent).toContain("Pronto"));
  });

  it("não duplica o envio quando o botão é acionado duas vezes", async () => {
    addMedia();
    await boot();
    const input = await startSession();
    fireEvent.change(input, { target: { value: "Olá" } });
    mocks.send.mockImplementation(() => new Promise<boolean>(() => {}));

    const sendButton = screen.getByRole("button", { name: "Enviar mensagem" });
    fireEvent.click(sendButton);
    fireEvent.click(sendButton);

    expect(mocks.send).toHaveBeenCalledTimes(1);
    expect(mocks.send).toHaveBeenCalledWith("Olá", "chat", "local-model", "", undefined, undefined, "ollama", true, true);
  });

  it("substitui a transcrição anterior em vez de a concatenar", async () => {
    addMedia();
    await boot();
    await startSession();

    let transcription = "Primeira";
    mocks.fetch.mockImplementation(async (url: string) => {
      if (url.includes("/voice/status")) return { ok: true, json: async () => status };
      if (url.includes("/voice/transcribe")) return { ok: true, json: async () => ({ text: transcription }) };
      return { ok: false, status: 500, json: async () => ({ detail: "erro" }) };
    });

    const input = screen.getByRole("textbox", { name: "Mensagem para o NEXUS" }) as HTMLTextAreaElement;
    fireEvent.click(screen.getByRole("button", { name: "Gravar voz" }));
    fireEvent.click(await screen.findByRole("button", { name: "Terminar gravação" }));
    await waitFor(() => expect(input.value).toBe("Primeira"));

    transcription = "Segunda";
    fireEvent.click(screen.getByRole("button", { name: "Gravar voz" }));
    fireEvent.click(await screen.findByRole("button", { name: "Terminar gravação" }));
    await waitFor(() => expect(input.value).toBe("Segunda"));
  });

  it("silenciar impede a abertura do microfone", async () => {
    addMedia();
    await boot();
    await startSession();

    fireEvent.click(screen.getByRole("button", { name: "Silenciar" }));

    expect((screen.getByTestId("voice-mic") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("voice-state").textContent).toContain("Microfone silenciado");
  });

  it("mãos-livres não abre o microfone antes de existir um turno", async () => {
    const media = addMedia();
    await boot();
    await startSession();

    fireEvent.click(screen.getByRole("checkbox", { name: /Mãos-livres/ }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(media.getUserMedia).not.toHaveBeenCalled();
  });
});

describe("NEXUS Voice — reprodução e cancelamento", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    FakeAudio.reset();
    FakeMediaRecorder.reset();
    mocks.stream.events = [];
    mocks.stream.streaming = false;
    mocks.stream.error = null;
    mocks.stream.busyOtherSession = false;
    mocks.create.mockResolvedValue({ id: "voice-session" });
    mocks.send.mockResolvedValue(true);
    mocks.models.mockImplementation(async (provider: string) => ({
      error: null,
      models: provider === "ollama" ? [{ id: "local-model", name: "Local", provider: "ollama" }] : [],
    }));
    mocks.fetch.mockImplementation(async (url: string) => {
      if (url.includes("/voice/status")) return { ok: true, json: async () => status };
      if (url.includes("/voice/transcribe")) return { ok: true, json: async () => ({ text: "Texto reconhecido" }) };
      if (url.includes("/voice/synthesize")) return { ok: true, blob: async () => new Blob(["wav"], { type: "audio/wav" }) };
      return { ok: false, status: 500, json: async () => ({ detail: "erro" }) };
    });
    objectUrls = installObjectUrls();
    installAudio();
  });

  afterEach(() => {
    while (mediaEnvironments.length) mediaEnvironments.pop()?.restore();
    objectUrls?.restore();
    objectUrls = null;
    FakeAudio.reset();
    vi.restoreAllMocks();
  });

  async function playResponse() {
    addMedia();
    const utils = await boot();
    await startSession();
    const input = screen.getByRole("textbox", { name: "Mensagem para o NEXUS" }) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Olá" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensagem" }));

    // The send resolves immediately; drive the mocked stream by hand.
    mocks.stream.streaming = true;
    utils.rerender(<VoiceWorkspace />);
    mocks.stream.events = [{ type: "token", content: "Olá, como posso ajudar?" }];
    mocks.stream.streaming = false;
    utils.rerender(<VoiceWorkspace />);

    await screen.findByRole("button", { name: "Parar voz" });
    return utils;
  }

  it("reproduz a resposta do turno uma única vez", async () => {
    await playResponse();
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1));
    expect(mocks.fetch.mock.calls.some(([url]) => String(url).includes("/voice/synthesize"))).toBe(true);
  });

  it("mãos-livres não captura a fala do bot e só reabre o microfone depois", async () => {
    const media = addMedia();
    const utils = await boot();
    await startSession();

    fireEvent.click(screen.getByRole("checkbox", { name: /Mãos-livres/ }));
    const input = screen.getByRole("textbox", { name: "Mensagem para o NEXUS" }) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Olá" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensagem" }));

    mocks.stream.streaming = true;
    utils.rerender(<VoiceWorkspace />);
    mocks.stream.events = [{ type: "token", content: "Resposta do NEXUS" }];
    mocks.stream.streaming = false;
    utils.rerender(<VoiceWorkspace />);

    await screen.findByRole("button", { name: "Parar voz" });
    expect(media.getUserMedia).not.toHaveBeenCalled();

    FakeAudio.instances.at(-1)?.finish();

    await waitFor(() => expect(media.getUserMedia).toHaveBeenCalledTimes(1));
    await screen.findByRole("button", { name: "Terminar gravação" });
  });

  it("não fica preso em processing quando a síntese de voz não está disponível", async () => {
    addMedia();
    mocks.fetch.mockImplementation(async (url: string) => {
      if (url.includes("/voice/status")) {
        return { ok: true, json: async () => ({ ...status, tts: { ...status.tts, ready: false } }) };
      }
      return { ok: false, status: 500, json: async () => ({ detail: "erro" }) };
    });

    const utils = await boot();
    await startSession();
    const input = screen.getByRole("textbox", { name: "Mensagem para o NEXUS" }) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Olá" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensagem" }));

    mocks.stream.streaming = true;
    utils.rerender(<VoiceWorkspace />);
    mocks.stream.events = [{ type: "token", content: "Resposta" }];
    mocks.stream.streaming = false;
    utils.rerender(<VoiceWorkspace />);

    await waitFor(() => expect(screen.getByTestId("voice-state").textContent).toContain("Pronto"));
    expect(FakeAudio.instances.length).toBe(0);
  });

  it("parar a voz pausa o áudio sem cancelar a resposta", async () => {
    await playResponse();
    await waitFor(() => expect(FakeAudio.instances.length).toBe(1));
    const audio = FakeAudio.instances[0];

    fireEvent.click(screen.getByRole("button", { name: "Parar voz" }));

    await waitFor(() => expect(audio.paused).toBe(true));
    expect(audio.pauseCalls).toBeGreaterThan(0);
    expect(mocks.cancel).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Parar voz" })).toBeNull();
  });

  it("cancelar a resposta aborta o áudio e informa o utilizador", async () => {
    addMedia();
    const utils = await boot();
    await startSession();
    mocks.stream.streaming = true;
    utils.rerender(<VoiceWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Cancelar resposta" }));

    expect(mocks.cancel).toHaveBeenCalled();
    expect(await screen.findByText(/Resposta cancelada/)).toBeTruthy();
  });

  it("mostra uma ação de desbloqueio quando o browser bloqueia o áudio", async () => {
    FakeAudio.nextPlayError = { name: "NotAllowedError" };
    await playResponse();
    await screen.findByRole("button", { name: "Ativar áudio" });

    fireEvent.click(screen.getByRole("button", { name: "Ativar áudio" }));

    await waitFor(() => expect(FakeAudio.instances.length).toBeGreaterThanOrEqual(2));
  });
});