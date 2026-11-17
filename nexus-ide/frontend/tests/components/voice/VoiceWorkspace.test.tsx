import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ send: vi.fn(), create: vi.fn(), fetch: vi.fn(), models: vi.fn(), stream: { events: [] as unknown[], streaming: false, error: null as string | null } }));
vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path, getProviderModels: mocks.models }));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: mocks.fetch }));
vi.mock("../../../hooks/useAgentStream", () => ({ useAgentStream: () => ({ ...mocks.stream, busyOtherSession: false, send: mocks.send, cancel: vi.fn() }) }));
vi.mock("../../../hooks/useChatSessions", () => ({ useChatSessionsStore: (selector: (state: { create: typeof mocks.create }) => unknown) => selector({ create: mocks.create }) }));
vi.mock("../../../components/chat/AgentTranscript", () => ({ default: () => <div>Transcrição do agente</div> }));

import VoiceWorkspace from "../../../components/voice/VoiceWorkspace";

const status = { stt: { ready: true, engine: "faster-whisper", models: [{ id: "base", installed: true }], devices: ["cpu"] }, tts: { ready: true, engine: "piper", voices: [{ id: "pt", name: "Português", language: "pt-PT" }], accent_note: "Sotaque não verificado." } };

describe("NEXUS Voice", () => {
  beforeEach(() => {
    localStorage.clear(); vi.clearAllMocks();
    mocks.stream.events = []; mocks.stream.streaming = false; mocks.stream.error = null;
    mocks.create.mockResolvedValue({ id: "voice-session" }); mocks.send.mockResolvedValue(true);
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => status });
    mocks.models.mockImplementation(async (provider: string) => ({ error: null, models: provider === "ollama" ? [{ id: "local-model", name: "Local", provider: "ollama" }] : [] }));
  });
  it("prefere o modelo STT predefinido pelo backend e respeita a escolha guardada", async () => {
    const models = [{ id: "base", installed: true }, { id: "small", installed: true }];
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ...status, stt: { ...status.stt, models, default_model: "small" } }) });
    const first = render(<VoiceWorkspace />);
    await waitFor(() => expect((screen.getByLabelText("Reconhecimento") as HTMLSelectElement).value).toBe("small"));
    fireEvent.change(screen.getByLabelText("Reconhecimento"), { target: { value: "base" } });
    await waitFor(() => expect(JSON.parse(localStorage.getItem("nexus.voice.preferences") ?? "{}").sttModel).toBe("base"));
    first.unmount();
    render(<VoiceWorkspace />);
    await waitFor(() => expect((screen.getByLabelText("Reconhecimento") as HTMLSelectElement).value).toBe("base"));
  });
  it("envia texto apenas com provider local, modelo concreto e modo seguro", async () => {
    render(<VoiceWorkspace />);
    await screen.findByRole("option", { name: /ollama · Local/ });
    fireEvent.change(screen.getByLabelText("Modelo local"), { target: { value: "ollama:local-model" } });
    fireEvent.click(screen.getByRole("button", { name: /Iniciar sessão/ }));
    const input = await screen.findByRole("textbox", { name: "Mensagem para o NEXUS" });
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(input, { target: { value: "Olá" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensagem" }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledWith("Olá", "chat", "local-model", "", undefined, undefined, "ollama", true, true));
  });
  it("exige seleção explícita e omite modelos de embeddings identificados", async () => {
    mocks.models.mockResolvedValue({ error: null, models: [
      { id: "big-24b", name: "Big 24B", provider: "lmstudio" },
      { id: "text-embedding-nomic", name: "text-embedding-nomic", provider: "lmstudio" },
      { id: "small-chat", name: "Small chat", provider: "lmstudio" },
    ] });
    render(<VoiceWorkspace />);
    await screen.findAllByRole("option", { name: /Big 24B/ });
    expect((screen.getByLabelText("Modelo local") as HTMLSelectElement).value).toBe("");
    expect(screen.queryByRole("option", { name: /text-embedding-nomic/ })).toBeNull();
    expect(screen.getAllByRole("option", { name: /Small chat/ }).length).toBeGreaterThan(0);
    expect(screen.getByText(/confirma que o modelo escolhido suporta conversa/i)).toBeTruthy();
  });
  it("permite escrever sem microfone e explica falta de suporte", async () => {
    render(<VoiceWorkspace />);
    await screen.findByRole("option", { name: "base" });
    fireEvent.click(screen.getByRole("button", { name: /Iniciar sessão/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Gravar voz" }));
    expect((await screen.findByRole("alert")).textContent).toContain("browser não permite gravar");
    expect((screen.getByRole("textbox", { name: "Mensagem para o NEXUS" }) as HTMLTextAreaElement).disabled).toBe(false);
  });
  it("revê a transcrição antes de a enviar e liberta o microfone", async () => {
    const stop = vi.fn();
    const original = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
    class Recorder {
      static isTypeSupported(type: string) { return type === "audio/webm"; }
      state = "inactive";
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      start() { this.state = "recording"; }
      stop() { this.state = "inactive"; this.ondataavailable?.({ data: new Blob(["voice"], { type: "audio/webm" }) }); this.onstop?.(); }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop }] })), enumerateDevices: vi.fn(async () => []) } });
    mocks.fetch.mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes("/transcribe") ? { text: "Texto reconhecido" } : status }));
    try {
      render(<VoiceWorkspace />);
      await screen.findByRole("option", { name: "base" });
      fireEvent.click(screen.getByRole("button", { name: /Iniciar sessão/ }));
      fireEvent.click(await screen.findByRole("button", { name: "Gravar voz" }));
      fireEvent.click(await screen.findByRole("button", { name: "Terminar gravação" }));
      await waitFor(() => expect((screen.getByRole("textbox", { name: "Mensagem para o NEXUS" }) as HTMLTextAreaElement).value).toBe("Texto reconhecido"));
      expect(stop).toHaveBeenCalled();
      expect(mocks.send).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
      if (original) Object.defineProperty(navigator, "mediaDevices", original);
      else Reflect.deleteProperty(navigator, "mediaDevices");
    }
  });
  it("não permite enviar sem um modelo local", async () => {
    mocks.models.mockResolvedValue({ error: null, models: [] });
    render(<VoiceWorkspace />);
    expect(await screen.findByText(/Não encontrei modelos locais/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Iniciar sessão/ }));
    const input = await screen.findByRole("textbox", { name: "Mensagem para o NEXUS" });
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(input, { target: { value: "Olá" } });
    expect((screen.getByRole("button", { name: "Enviar mensagem" }) as HTMLButtonElement).disabled).toBe(true);
    expect(mocks.send).not.toHaveBeenCalled();
  });
});
