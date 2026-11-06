import type { PropsWithChildren } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { navigationState } = vi.hoisted(() => ({ navigationState: { pathname: "/nexus" } }));

vi.mock("next/navigation", () => ({ usePathname: () => navigationState.pathname }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

import NexusSidebar from "../../../components/nexus/NexusSidebar";

describe("NexusSidebar", () => {
  beforeEach(() => {
    navigationState.pathname = "/nexus";
  });

  it("mostra apenas destinos de navegação que existem no projeto", () => {
    render(<NexusSidebar />);

    const validRoutes = new Set([
      "/nexus", "/nexus/hitl", "/dashboard/tasks", "/documents", "/search", "/editor",
      "/tools", "/models", "/analytics", "/settings",
    ]);
    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(validRoutes.has(link.getAttribute("href") ?? "")).toBe(true);
    expect(screen.getByText("NEXUS IDE")).toBeTruthy();
    expect(screen.getByText("Workspace")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Tarefas" }).getAttribute("href")).toBe("/dashboard/tasks");
    expect(screen.queryByRole("link", { name: "Agentes" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Fluxos" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Memória vetorial" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Browser Sessions" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Vector DB" })).toBeNull();
  });

  it("marca apenas a página atual e não confunde o dashboard com uma página irmã", () => {
    navigationState.pathname = "/nexus/hitl";
    render(<NexusSidebar />);

    expect(screen.getByRole("link", { name: "Aprovações" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("aria-current")).toBeNull();
  });

  it("abre o menu mobile, fecha com Escape e volta a fechar ao mudar de rota", () => {
    navigationState.pathname = "/nexus";
    const { rerender } = render(<NexusSidebar />);

    const menu = screen.getByRole("button", { name: "Abrir menu" });
    const aside = document.getElementById("nexus-secondary-navigation");
    expect(aside).toBeTruthy();
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    // `inert`/`aria-hidden` are now gated on a real mobile media query
    // (`useMediaQuery("(max-width: 767px)")`) instead of being applied to every
    // closed drawer: on desktop the navigation must stay focusable. jsdom
    // reports no match for the query, i.e. desktop behaviour — not inert.
    expect(aside?.hasAttribute("inert")).toBe(false);

    fireEvent.click(menu);
    expect(screen.getByRole("button", { name: "Fechar menu" }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Abrir menu" }).getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
    navigationState.pathname = "/dashboard/tasks";
    rerender(<NexusSidebar />);
    expect(screen.getByRole("link", { name: "Tarefas" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("button", { name: "Abrir menu" }).getAttribute("aria-expanded")).toBe("false");
  });
});
