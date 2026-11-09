import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import SettingsPage from "../../app/settings/page";
import { getSettings, saveSettings, getProviderCatalog, validateProviderKey } from "../../lib/api";

vi.mock("../../components/layout/AppShell", () => ({ default: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock("../../lib/api", () => ({ getSettings: vi.fn(), saveSettings: vi.fn(), getProviderCatalog: vi.fn(), validateProviderKey: vi.fn() }));

const catalog = [{ id: "opencode_go", label: "OpenCode Go", key_setting: "opencode_go_api_key", requires_key: true, api_key_set: true, base_url: "", docs: "" }];
describe("Definições e APIs", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear();
    vi.mocked(getSettings).mockResolvedValue({ llm_provider: "opencode_go", brave_api_key: "ABCD****WXYZ", opencode_go_api_key: "masked****secret", free_only: false });
    vi.mocked(getProviderCatalog).mockResolvedValue(catalog);
    vi.mocked(saveSettings).mockResolvedValue({});
  });
  it("preserva chaves ocultas e envia apenas alterações explícitas", async () => {
    render(<SettingsPage />);
    const key = await screen.findByLabelText("Chave API") as HTMLInputElement;
    expect(key.value).toBe("");
    fireEvent.change(key, { target: { value: "new-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));
    await waitFor(() => expect(saveSettings).toHaveBeenCalledWith({ opencode_go_api_key: "new-key" }));
    await waitFor(() => expect(key.value).toBe(""));
  });
  it("testa uma chave nova sem a guardar", async () => {
    vi.mocked(validateProviderKey).mockResolvedValue({ provider: "opencode_go", valid: true, error: null, models_count: 3 });
    render(<SettingsPage />);
    fireEvent.change(await screen.findByLabelText("Chave API"), { target: { value: "new-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Testar ligação" }));
    expect(await screen.findByText(/chave ainda por guardar/)).toBeTruthy();
    expect(validateProviderKey).toHaveBeenCalledWith("opencode_go", "new-key");
    expect(saveSettings).not.toHaveBeenCalled();
  });
  it("mantém as alterações após falha sem as guardar no navegador", async () => {
    vi.mocked(saveSettings).mockRejectedValue(new Error("offline"));
    render(<SettingsPage />);
    const input = await screen.findByLabelText("Brave Search API Key") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "brave-test-key-1234" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));
    await screen.findByText(/Não foi possível guardar no servidor/);
    expect(input.value).toBe("brave-test-key-1234");
    expect(localStorage.getItem("nexus_settings")).toBeNull();
  });
  it("impede gravação quando não consegue carregar as definições", async () => {
    vi.mocked(getSettings).mockRejectedValue(new Error("offline"));
    render(<SettingsPage />);
    await screen.findByText(/Não foi possível carregar as definições/);
    expect((screen.getByRole("button", { name: "Guardar alterações" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
