import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => vi.fn());

vi.mock("../../../lib/auth", () => ({ authenticatedFetch: fetchMock }));
vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path }));
vi.mock("../../../components/chat/MessageBubble", () => ({
  AssistantMarkdown: ({ text }: { text: string }) => <div>{text}</div>,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => <a href={href} {...props}>{children}</a>,
}));
vi.mock("next/image", () => ({
  default: (props: { alt?: string }) => <span data-alt={props.alt ?? ""} />,
}));

import GroupWorkspace from "../../../components/bots/GroupWorkspace";

const kilo = "O Kilo está bloqueado pela política só gratuita.";

const bots = [
  { id: "forge", session_id: "s1", name: "FORGE", description: "Programação", instructions: "", provider: "kilo", model: "free", archived: false, last_message: null, last_active_at: "" },
  { id: "debug", session_id: "s2", name: "Debugger", description: "Diagnóstico", instructions: "", provider: "kilo", model: "free", archived: false, last_message: null, last_active_at: "" },
];

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body, body: null };
}

describe("GroupWorkspace incidents", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    fetchMock.mockImplementation(async (path: string) => {
      if (path.endsWith("/api/bot-groups")) {
        return jsonResponse({ groups: [{ id: "g1", name: "123", bot_ids: ["forge", "debug"], last_message: "falhou" }] });
      }
      if (path.includes("/messages")) {
        return jsonResponse({
          messages: [
            { id: "u1", role: "user", content: "bom dia", bot_id: null, bot_name: null, created_at: "2026-11-09T10:00:00Z" },
            { id: "e1", role: "error", content: kilo, bot_id: "forge", bot_name: "FORGE", created_at: "2026-11-09T10:00:01Z" },
            { id: "e2", role: "error", content: kilo, bot_id: "debug", bot_name: "Debugger", created_at: "2026-11-09T10:00:02Z" },
          ],
          has_more: false,
          next_before: null,
        });
      }
      if (path.includes("/runs")) return jsonResponse({ runs: [] });
      return jsonResponse({});
    });
  });

  it("mostra um incidente com contagem em vez de repetir o mesmo erro", async () => {
    render(<GroupWorkspace bots={bots} onBack={() => undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: /123/ }));
    expect(await screen.findByText("Falha de provider nesta volta")).toBeTruthy();
    expect(screen.getByText("2 ocorrências")).toBeTruthy();
    expect(screen.getAllByText(kilo)).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Ver configuração" }).getAttribute("href")).toBe("/settings");
    fireEvent.click(screen.getByRole("button", { name: "Detalhes técnicos" }));
    expect(screen.getByText(/FORGE · e1/)).toBeTruthy();
    expect(screen.getByText(/Debugger · e2/)).toBeTruthy();
  });

  it("abre a escolha de modelo sem trocar o provider sozinho", async () => {
    const openBot = vi.fn();
    render(<GroupWorkspace bots={bots} onBack={() => undefined} onOpenBot={openBot} />);
    fireEvent.click(await screen.findByRole("button", { name: /123/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Escolher outro modelo" }));
    expect(screen.getByRole("dialog", { name: "Escolher outro modelo" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Abrir FORGE" }));
    expect(openBot).toHaveBeenCalledWith("forge");
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/messages") && call[1]?.method === "POST")).toBe(false);
  });
});
