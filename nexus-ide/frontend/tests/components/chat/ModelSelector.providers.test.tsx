import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ModelSelector from "../../../components/chat/ModelSelector";
import { useModelStore, type Model } from "../../../stores/modelStore";

it("retains the provider when different providers expose the same model id", () => {
  const choose = vi.fn();
  const models: Model[] = ["kilo", "openrouter"].map((provider) => ({
    id: "shared/model", name: `${provider} model`, provider,
    tier: "medium", size_gb: 0, status: "available",
  }));
  useModelStore.setState({ activeModel: "", activeProvider: "", models,
    providerStatus: [], modelsLoaded: true, modelsLoading: false, modelsError: null,
    loadModels: vi.fn().mockResolvedValue(undefined), setActiveModel: choose });
  render(<ModelSelector />);
  fireEvent.click(screen.getByRole("button", { name: /automático/i }));
  const dialog = screen.getByRole("dialog", { name: "Selecionar modelo" });
  fireEvent.click(within(dialog).getByRole("button", { name: /openrouter model/i }));
  expect(choose).toHaveBeenCalledWith("shared/model", "openrouter");
});
