import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const navigationMocks = vi.hoisted(() => ({
  replace: vi.fn(),
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigationMocks.replace }),
  useSearchParams: () => navigationMocks.searchParams,
}));

import SwarmPanel from "../../../components/swarm/SwarmPanel";

describe("SwarmPanel dashboard handoff", () => {
  beforeEach(() => {
    navigationMocks.replace.mockReset();
    navigationMocks.searchParams = new URLSearchParams(
      `prompt=${encodeURIComponent("Inspecionar a pesquisa de imagens")}`,
    );

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ modes: {}, agents: {}, runs: [], skills: [] }),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("prefills the objective from the URL without launching a run", async () => {
    render(<SwarmPanel sessionId="default" />);

    const objective = screen.getByRole("textbox", { name: "Objective" }) as HTMLTextAreaElement;
    await waitFor(() => {
      expect(objective.value).toBe("Inspecionar a pesquisa de imagens");
    });

    expect(navigationMocks.replace).toHaveBeenCalledWith("/swarm", { scroll: false });

    const fetchMock = vi.mocked(fetch);
    const launchedRun = fetchMock.mock.calls.some(
      ([input, init]) => String(input).endsWith("/api/swarm/run") && init?.method === "POST",
    );
    expect(launchedRun).toBe(false);
  });
});
