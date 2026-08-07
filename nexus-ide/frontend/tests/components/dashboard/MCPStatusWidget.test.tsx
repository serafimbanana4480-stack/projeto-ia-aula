import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import MCPStatusWidget from "../../../components/dashboard/MCPStatusWidget";
import * as api from "../../../lib/api";

describe("MCPStatusWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("mostra estado vazio e link para ligar o primeiro servidor", async () => {
    vi.spyOn(api, "getMCPConnectors").mockResolvedValue({
      connectors: [],
      summary: { total: 0, enabled: 0, healthy: 0, warning: 0, error: 0, untested: 0 },
    });

    render(<MCPStatusWidget />);

    await waitFor(() => {
      expect(screen.getByText("Nenhum conector MCP configurado")).toBeDefined();
    });
    expect(screen.getByText(/Ligar o primeiro servidor/)).toBeDefined();
  });

  it("mostra contagens e conectores quando existem dados", async () => {
    vi.spyOn(api, "getMCPConnectors").mockResolvedValue({
      connectors: [
        {
          id: "mcp_1",
          name: "Filesystem",
          template_id: "filesystem",
          description: "",
          transport: "stdio",
          command: "npx",
          args: [],
          env: {},
          url: "",
          enabled: true,
          created_at: 0,
          updated_at: 0,
          last_test_status: "ok",
          last_test_detail: "",
          last_tested_at: null,
        },
      ],
      summary: { total: 1, enabled: 1, healthy: 1, warning: 0, error: 0, untested: 0 },
    });

    render(<MCPStatusWidget />);

    await waitFor(() => {
      expect(screen.getByText("Filesystem")).toBeDefined();
    });
    expect(screen.getByText("Gerir conectores")).toBeDefined();
  });
});
