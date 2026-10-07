import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import UsageWidget from "../../../components/dashboard/UsageWidget";

const { mockAuthenticatedFetch } = vi.hoisted(() => ({
  mockAuthenticatedFetch: vi.fn(),
}));

vi.mock("../../../lib/api", () => ({
  apiUrl: (path: string) => path,
}));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: mockAuthenticatedFetch }));

vi.mock("recharts", () => ({
  PieChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Pie: () => null,
  Cell: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Legend: () => null,
}));

const trackerUsage = {
  total_tokens: 150,
  total_tokens_in: 120,
  total_tokens_out: 30,
  total_cost: 0.0042,
  by_model: { "gpt-mini": { total_tokens: 150, cost: 0.0042 } },
  by_provider: { openai: 150 },
  range_seconds: 86_400,
  generated_at: 1_800_000_000,
  currency: "USD",
  cost_is_estimated: true,
};

describe("UsageWidget", () => {
  beforeEach(() => {
    mockAuthenticatedFetch.mockReset();
    mockAuthenticatedFetch.mockResolvedValue({ ok: true, json: async () => trackerUsage });
  });

  it("labels estimated costs and ranks providers recorded by the tracker", async () => {
    render(<UsageWidget />);

    expect(await screen.findByText("openai")).toBeTruthy();
    expect(screen.getAllByText("Custo estimado").length).toBeGreaterThan(0);
    expect(screen.getByText("Top providers")).toBeTruthy();
    expect(screen.getByText("tracker em memória", { exact: false })).toBeTruthy();
    expect(screen.queryByText("Top agentes")).toBeNull();

    const periodGroup = screen.getByRole("group", { name: "Intervalo de tempo" });
    const weekButton = screen.getByRole("button", { name: "7d" });
    expect(periodGroup).toBeTruthy();
    expect(weekButton.getAttribute("aria-pressed")).toBe("false");
    expect(weekButton.className).toContain("min-h-9");

    fireEvent.click(weekButton);
    await waitFor(() => expect(mockAuthenticatedFetch).toHaveBeenCalledTimes(2));
    expect(mockAuthenticatedFetch).toHaveBeenNthCalledWith(
      1,
      "/api/metrics/usage?range=24h",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(mockAuthenticatedFetch).toHaveBeenNthCalledWith(
      2,
      "/api/metrics/usage?range=7d",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(weekButton.getAttribute("aria-pressed")).toBe("true");
  });
});
