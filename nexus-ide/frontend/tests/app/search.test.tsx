import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import SearchPage from "../../app/search/page";
import { webImageSearch, webSearch } from "../../lib/api";

vi.mock("../../components/layout/AppShell", () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("../../lib/api", () => ({
  ApiError: class ApiError extends Error {
    constructor(message: string, public status: number, public responseText?: string) {
      super(message);
    }
  },
  webImageSearch: vi.fn(),
  webSearch: vi.fn(),
}));

describe("SearchPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/");
  });

  it("explica o limite da pesquisa recebida no parâmetro q sem chamar a API", async () => {
    window.history.replaceState({}, "", `/search?q=${"a".repeat(401)}`);

    render(<SearchPage />);

    expect((await screen.findByRole("alert")).textContent).toContain("até 400 caracteres");
    expect(webSearch).not.toHaveBeenCalled();
    expect(webImageSearch).not.toHaveBeenCalled();
  });

  it("mostra cartões de imagem ligados à origem e usa fallback para miniaturas quebradas", async () => {
    vi.mocked(webImageSearch).mockResolvedValue({
      query: "capacete",
      hits: [
        {
          title: "Capacete de estrada",
          url: "https://example.org/helmet",
          thumbnail_url: "https://imgs.search.brave.com/helmet",
          source: "example.org",
          width: 640,
          height: 480,
        },
      ],
      count: 1,
      configured: true,
      provider: "brave",
    });

    render(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Termos de pesquisa" }), {
      target: { value: "capacete" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Pesquisar" }));

    const sourceLink = await screen.findByRole("link", { name: /Capacete de estrada/ });
    expect(sourceLink.getAttribute("href")).toBe("https://example.org/helmet");
    expect(screen.getByText("example.org")).toBeTruthy();
    expect(screen.getByText(/Confirma a licença/)).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("1 imagem para");

    fireEvent.error(screen.getByRole("img", { name: "Capacete de estrada" }));
    expect(await screen.findByText("Pré-visualização indisponível")).toBeTruthy();
  });

  it("explica quando a pesquisa de imagens não está configurada", async () => {
    vi.mocked(webImageSearch).mockResolvedValue({
      query: "capacete",
      hits: [],
      count: 0,
      configured: false,
      error: "Pesquisa de imagens indisponível: falta configurar a chave Brave.",
    });

    render(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Termos de pesquisa" }), {
      target: { value: "capacete" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Pesquisar" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Abrir definições/ }).getAttribute("href")).toBe("/settings");
    expect(webSearch).not.toHaveBeenCalled();
  });

  it("mostra indisponibilidade do fornecedor como erro, não como pesquisa sem resultados", async () => {
    vi.mocked(webSearch).mockRejectedValue(new Error("provider returned 502"));

    render(<SearchPage />);
    const input = screen.getByRole("searchbox", { name: "Termos de pesquisa" });
    fireEvent.change(input, { target: { value: "capacete" } });
    fireEvent.submit(input.closest("form")!);

    expect((await screen.findByRole("alert")).textContent).toContain("A pesquisa falhou");
    expect(screen.queryByText(/Sem resultados para/)).toBeNull();
  });

  it("dá um caminho para corrigir uma chave Brave recusada", async () => {
    vi.mocked(webImageSearch).mockResolvedValue({
      query: "capacete",
      hits: [],
      count: 0,
      configured: true,
      error: "A chave Brave não foi aceite. Confirma a configuração.",
      error_code: "invalid_credentials",
    });

    render(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Termos de pesquisa" }), {
      target: { value: "capacete" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Pesquisar" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Abrir definições/ }).getAttribute("href")).toBe("/settings");
  });

  it("keeps untrusted image previews and web URLs from becoming active links", async () => {
    vi.mocked(webImageSearch).mockResolvedValue({
      query: "capacete",
      hits: [{
        title: "Imagem com preview desconhecido",
        url: "https://example.org/source",
        thumbnail_url: "https://evil.example/preview.jpg",
        source: "example.org",
        width: null,
        height: null,
      }, {
        title: "Origem com protocolo inseguro",
        url: "javascript:alert(1)",
        thumbnail_url: "https://imgs.search.brave.com/safe-preview",
        source: "invalid.test",
        width: null,
        height: null,
      }],
      count: 2,
      configured: true,
    });

    render(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Termos de pesquisa" }), {
      target: { value: "capacete" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Pesquisar" }));

    const imageTitle = await screen.findByText("Imagem com preview desconhecido");
    expect(imageTitle.closest("a")?.getAttribute("href")).toBe("https://example.org/source");
    expect(screen.queryByRole("img", { name: "Imagem com preview desconhecido" })).toBeNull();
    expect(screen.getByText("Pré-visualização indisponível")).toBeTruthy();
    expect(screen.queryByText("Origem com protocolo inseguro")).toBeNull();
    expect(screen.getByText(/1 imagem para/)).toBeTruthy();

    vi.mocked(webSearch).mockResolvedValue({
      query: "capacete",
      count: 2,
      hits: [
        { title: "Seguro", url: "https://example.org/safe" },
        { title: "Inseguro", url: "javascript:alert(1)" },
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "Web" }));
    const safeTitle = await screen.findByText("Seguro");
    expect(safeTitle.closest("a")?.getAttribute("href")).toBe("https://example.org/safe");
    expect(screen.getByText("Inseguro").closest("a")).toBeNull();
  });

  it("does not report no results when every image source is filtered for safety", async () => {
    vi.mocked(webImageSearch).mockResolvedValue({
      query: "capacete",
      hits: [{
        title: "Origem bloqueada",
        url: "javascript:alert(1)",
        thumbnail_url: "https://imgs.search.brave.com/helmet",
        source: "origem não segura",
        width: 640,
        height: 480,
      }],
      count: 1,
      configured: true,
    });

    render(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Termos de pesquisa" }), {
      target: { value: "capacete" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Pesquisar" }));

    const filteredState = await screen.findByText(
      "A pesquisa devolveu imagens, mas nenhuma tinha uma página de origem segura para abrir.",
    );
    expect(filteredState.getAttribute("role")).toBe("status");
    expect(screen.queryByText(/Sem resultados para/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Resultados de imagens" })).toBeNull();
  });

  it("paginas os resultados de imagens e mantém a navegação acessível", async () => {
    vi.mocked(webImageSearch).mockResolvedValue({
      query: "bicicleta",
      hits: Array.from({ length: 50 }, (_, index) => ({
        title: `Imagem ${index + 1}`,
        url: `https://example.org/image-${index + 1}`,
        thumbnail_url: `https://imgs.search.brave.com/thumb-${index + 1}`,
        source: "example.org",
        width: 640,
        height: 480,
      })),
      count: 50,
      configured: true,
      provider: "brave",
    });

    render(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Termos de pesquisa" }), {
      target: { value: "bicicleta" },
    });
    fireEvent.submit(screen.getByRole("searchbox").closest("form")!);

    const firstImageTitle = await screen.findByText("Imagem 1");
    expect(firstImageTitle.closest("a")?.getAttribute("href")).toBe("https://example.org/image-1");
    expect(screen.getByText("Imagem 25")).toBeTruthy();
    expect(screen.queryByText("Imagem 26")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Seguinte" }));
    const finalImageTitle = await screen.findByText("Imagem 26");
    expect(finalImageTitle.closest("a")?.getAttribute("href")).toBe("https://example.org/image-26");
    expect(screen.getByText("Imagem 50")).toBeTruthy();
    expect(screen.queryByText("Imagem 25")).toBeNull();
    expect(screen.getByText("Página 2 de 2")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Anterior" }).hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "Seguinte" }).hasAttribute("disabled")).toBe(true);
  });

  it("pagina os resultados Web recebidos e pede a maior janela suportada pela API", async () => {
    vi.mocked(webSearch).mockResolvedValue({
      query: "NEXUS",
      count: 12,
      hits: Array.from({ length: 12 }, (_, index) => ({
        title: `Resultado ${index + 1}`,
        url: `https://example.org/result-${index + 1}`,
      })),
    });

    render(<SearchPage />);
    const input = screen.getByRole("searchbox", { name: "Termos de pesquisa" });
    fireEvent.change(input, { target: { value: "NEXUS" } });
    fireEvent.submit(input.closest("form")!);

    expect(await screen.findByText("Resultado 1")).toBeTruthy();
    expect(screen.getByText("Resultado 10")).toBeTruthy();
    expect(screen.queryByText("Resultado 11")).toBeNull();
    expect(vi.mocked(webSearch).mock.calls.at(-1)?.[0]).toEqual({ query: "NEXUS", limit: 50 });

    fireEvent.click(screen.getByRole("button", { name: "Seguinte" }));
    expect(await screen.findByText("Resultado 11")).toBeTruthy();
    expect(screen.queryByText("Resultado 1")).toBeNull();
    expect(screen.getByText("Página 2 de 2")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Anterior" }).hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "Seguinte" }).hasAttribute("disabled")).toBe(true);
  });

  it("cancela uma pesquisa ultrapassada ao trocar de Web para Imagens", async () => {
    let finishWebSearch: ((value: Awaited<ReturnType<typeof webSearch>>) => void) | undefined;
    const staleWebResult = new Promise<Awaited<ReturnType<typeof webSearch>>>((resolve) => {
      finishWebSearch = resolve;
    });
    vi.mocked(webSearch).mockReturnValue(staleWebResult);
    vi.mocked(webImageSearch).mockResolvedValue({
      query: "capacete",
      hits: [{
        title: "Resultado atual",
        url: "https://example.org/current",
        thumbnail_url: "https://imgs.search.brave.com/current",
        source: "example.org",
        width: null,
        height: null,
      }],
      count: 1,
      configured: true,
    });

    render(<SearchPage />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Termos de pesquisa" }), {
      target: { value: "capacete" },
    });
    fireEvent.submit(screen.getByRole("searchbox").closest("form")!);
    const webSignal = vi.mocked(webSearch).mock.calls[0]?.[1];

    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    expect(webSignal?.aborted).toBe(true);
    expect(await screen.findByRole("link", { name: /Resultado atual/ })).toBeTruthy();

    await act(async () => {
      finishWebSearch?.({ query: "capacete", hits: [{ title: "Obsoleto", url: "https://example.org/old" }], count: 1 });
    });
    expect(screen.queryByText("Obsoleto")).toBeNull();
    expect(screen.getByText(/Pesquisa visual · resultados externos/)).toBeTruthy();
  });

  it("permite substituir uma pesquisa lenta e ignora a resposta antiga", async () => {
    let finishOldSearch: ((value: Awaited<ReturnType<typeof webSearch>>) => void) | undefined;
    const oldSearch = new Promise<Awaited<ReturnType<typeof webSearch>>>((resolve) => {
      finishOldSearch = resolve;
    });
    vi.mocked(webSearch)
      .mockReturnValueOnce(oldSearch)
      .mockResolvedValueOnce({
        query: "bicicleta",
        count: 1,
        hits: [{ title: "Resultado atual", url: "https://example.org/current" }],
      });

    render(<SearchPage />);
    const input = screen.getByRole("searchbox", { name: "Termos de pesquisa" });
    const form = input.closest("form")!;
    fireEvent.change(input, { target: { value: "capacete" } });
    fireEvent.submit(form);
    const oldSignal = vi.mocked(webSearch).mock.calls[0]?.[1];

    fireEvent.change(input, { target: { value: "bicicleta" } });
    fireEvent.submit(form);

    expect(oldSignal?.aborted).toBe(true);
    expect(await screen.findByText("Resultado atual")).toBeTruthy();
    await act(async () => {
      finishOldSearch?.({
        query: "capacete",
        count: 1,
        hits: [{ title: "Resultado obsoleto", url: "https://example.org/old" }],
      });
    });
    expect(screen.queryByText("Resultado obsoleto")).toBeNull();
  });

  it("usa o texto atual ao mudar de tipo de pesquisa", async () => {
    vi.mocked(webSearch).mockResolvedValue({
      query: "capacete",
      count: 1,
      hits: [{ title: "Pesquisa anterior", url: "https://example.org/old" }],
    });
    vi.mocked(webImageSearch).mockResolvedValue({
      query: "bicicleta",
      hits: [],
      count: 0,
      configured: true,
    });

    render(<SearchPage />);
    const input = screen.getByRole("searchbox", { name: "Termos de pesquisa" });
    fireEvent.change(input, { target: { value: "capacete" } });
    fireEvent.submit(input.closest("form")!);
    expect(await screen.findByText("Pesquisa anterior")).toBeTruthy();

    fireEvent.change(input, { target: { value: "bicicleta" } });
    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));

    expect(await screen.findByText(/Sem resultados para/)).toBeTruthy();
    expect(vi.mocked(webImageSearch).mock.calls.at(-1)?.[0].query).toBe("bicicleta");
  });
});
