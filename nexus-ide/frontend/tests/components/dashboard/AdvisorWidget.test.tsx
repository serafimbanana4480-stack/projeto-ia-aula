import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdvisorWidget from "../../../components/dashboard/AdvisorWidget";
import { authenticatedFetch } from "../../../lib/auth";

vi.mock("../../../lib/api", () => ({
  apiUrl: (path: string) => path,
}));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: vi.fn() }));

describe("AdvisorWidget", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading before deciding there are no advisor sessions", async () => {
    let resolveResponse!: (response: Response) => void;
    vi.mocked(authenticatedFetch).mockReturnValue(new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    }));

    render(<AdvisorWidget />);

    expect(screen.getByRole("status").textContent).toContain("A carregar estado do advisor");
    expect(screen.queryByText(/Sem sessões do advisor/)).toBeNull();
    expect(authenticatedFetch).toHaveBeenCalledWith(
      "/api/advanced-modes/advisor-infinity",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    await act(async () => {
      resolveResponse(new Response(JSON.stringify({
          mode_id: "advisor-infinity",
          display_name: "Advisor Infinity",
          description: "Estado de revisão",
          color: "amber",
          active: false,
          session_count: 0,
          sessions: [],
          available: true,
        }), { status: 200, headers: { "content-type": "application/json" } }));
    });

    expect(await screen.findByText(/Sem sessões do advisor/)).toBeDefined();
  });
});
