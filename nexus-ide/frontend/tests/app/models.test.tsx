import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ModelsPage from "../../app/models/page";
import { useModelStore, type Model } from "../../stores/modelStore";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("../../components/layout/AppShell", () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

const models: Model[] = [
  {
    id: "openai/gpt-test",
    name: "GPT Test",
    tier: "CODER",
    size_gb: 0,
    provider: "openai",
    status: "available",
    contextWindow: 128_000,
    inputPricePer1M: 0.5,
    capabilities: ["chat", "code"],
  },
  {
    id: "local/vision-test",
    name: "Vision Test",
    tier: "VISION",
    size_gb: 0,
    provider: "ollama",
    status: "available",
    contextWindow: 32_000,
    capabilities: ["chat", "vision"],
  },
];

describe("ModelsPage", () => {
  const loadModels = vi.fn().mockResolvedValue(undefined);
  const setActiveModel = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useModelStore.setState({
      activeModel: "",
      activeProvider: "",
      models,
      providerStatus: [],
      modelsLoaded: true,
      modelsLoading: false,
      modelsError: null,
      loadModels,
      setActiveModel,
    });
  });

  it("loads the catalog and renders available models", async () => {
    render(<ModelsPage />);

    await waitFor(() => expect(loadModels).toHaveBeenCalledWith());
    expect(screen.getByRole("heading", { name: "Modelos IA" })).toBeTruthy();
    expect(screen.getByText("GPT Test")).toBeTruthy();
    expect(screen.getByText("Vision Test")).toBeTruthy();
  });

  it("filters by search and provider", () => {
    render(<ModelsPage />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Pesquisar modelos" }), {
      target: { value: "Vision" },
    });

    expect(screen.getByText("Vision Test")).toBeTruthy();
    expect(screen.queryByText("GPT Test")).toBeNull();

    fireEvent.change(screen.getByRole("searchbox", { name: "Pesquisar modelos" }), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar por provider" }), {
      target: { value: "openai" },
    });

    expect(screen.getByText("GPT Test")).toBeTruthy();
    expect(screen.queryByText("Vision Test")).toBeNull();
  });

  it("selects the concrete model before opening chat", () => {
    render(<ModelsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Usar GPT Test" }));

    expect(setActiveModel).toHaveBeenCalledWith("openai/gpt-test", "openai");
    expect(push).toHaveBeenCalledWith("/");
  });

  it("surfaces catalog errors with a route to settings", () => {
    useModelStore.setState({ models: [], modelsLoaded: true, modelsError: "OpenAI: indisponível" });
    render(<ModelsPage />);

    expect(screen.getByRole("alert").textContent).toContain("OpenAI: indisponível");
    expect(screen.getByRole("link", { name: "Rever configuração" }).getAttribute("href")).toBe("/settings");
  });
});
