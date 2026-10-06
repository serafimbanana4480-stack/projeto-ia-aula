import type { PropsWithChildren } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { navigationState } = vi.hoisted(() => ({ navigationState: { pathname: "/" } }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useRouter: () => ({ prefetch: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, prefetch: _prefetch, ...props }: PropsWithChildren<{ href: string; prefetch?: boolean }>) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

import Sidebar from "../../../components/layout/Sidebar";

describe("Sidebar", () => {
  beforeEach(() => {
    navigationState.pathname = "/";
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("min-width: 768px") ? false : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });

  it("liga os itens de navegação a rotas que existem", () => {
    render(<Sidebar />);

    const validRoutes = new Set([
      "/", "/dashboard", "/dashboard/tasks", "/editor", "/projects", "/swarm", "/analysis",
      "/analytics", "/models", "/mcp", "/tools", "/database", "/documents", "/pdf",
      "/search", "/scraping", "/settings",
    ]);
    for (const link of screen.getAllByRole("link", { hidden: true })) {
      expect(validRoutes.has(link.getAttribute("href") ?? "")).toBe(true);
    }
  });

  it("seleciona a rota ativa e abre e fecha o menu no telemóvel", () => {
    navigationState.pathname = "/dashboard/tasks";
    const { rerender } = render(<Sidebar />);

    expect(screen.getByRole("link", { name: "Tarefas", hidden: true }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Dashboard", hidden: true }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("button", { name: "Abrir menu" }).getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
    expect(screen.getByRole("button", { name: "Fechar menu" }).getAttribute("aria-expanded")).toBe("true");
    navigationState.pathname = "/projects";
    rerender(<Sidebar />);
    expect(screen.getByRole("button", { name: "Abrir menu" }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("link", { name: "Projetos", hidden: true }).getAttribute("aria-current")).toBe("page");
  });
});
