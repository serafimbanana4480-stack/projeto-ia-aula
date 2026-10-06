import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RuntimeReadinessBanner from "../../../components/dashboard/RuntimeReadinessBanner";

function response(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("RuntimeReadinessBanner", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shows critical disk pressure even while the liveness API is reachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      status: "not_ready",
      dependencies: { database: "ready", disk: "not_ready", agent_pool: "ready" },
      disk_pressure: {
        status: "critical",
        write_blocked: true,
        snapshot: { free_percent: 1.913 },
      },
    })));

    render(<RuntimeReadinessBanner />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Armazenamento crítico/);
    expect(alert.textContent).toContain("1,9% livre");
    expect(alert.textContent).toMatch(/guard de escrita está ativo/);
  });

  it("keeps the dashboard quiet when readiness and disk are healthy", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      status: "ready",
      dependencies: { database: "ready", disk: "ready" },
      disk_pressure: {
        status: "normal",
        write_blocked: false,
        snapshot: { free_percent: 42 },
      },
    })));

    const { container } = render(<RuntimeReadinessBanner />);
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(container.childElementCount).toBe(0);
  });

  it("does not claim readiness when the probe cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    render(<RuntimeReadinessBanner />);

    const status = await screen.findByRole("status");
    expect(status.textContent).toMatch(/Não foi possível confirmar a prontidão/);
  });

  it("times out a stalled probe and retries on the next interval", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url: string, options?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<RuntimeReadinessBanner />);

    await act(async () => { await vi.advanceTimersByTimeAsync(8_000); });
    expect(screen.getByRole("status").textContent).toMatch(/Não foi possível confirmar a prontidão/);
    await act(async () => { await vi.advanceTimersByTimeAsync(22_000); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("refreshes readiness periodically without overlapping requests", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(response({
      status: "ready",
      dependencies: { database: "ready", disk: "ready" },
      disk_pressure: { status: "normal", write_blocked: false, snapshot: { free_percent: 42 } },
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<RuntimeReadinessBanner />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
