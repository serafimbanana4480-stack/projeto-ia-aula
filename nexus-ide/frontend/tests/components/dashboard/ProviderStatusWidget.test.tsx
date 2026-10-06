import { describe, expect, it } from "vitest";
import {
  getStatusInfo,
  successRatePercent,
} from "../../../components/dashboard/ProviderStatusWidget";

describe("ProviderStatusWidget metrics", () => {
  it("does not invent a success rate for an unavailable provider", () => {
    const info = { healthy: false };

    expect(getStatusInfo(info)).toEqual({ tone: "danger", label: "Indisponível" });
    expect(successRatePercent(info)).toBeNull();
  });

  it("labels an unmeasured provider separately from a healthy provider", () => {
    expect(getStatusInfo({})).toEqual({ tone: "warning", label: "Não verificado" });
    expect(successRatePercent({ success_rate: 0.875 })).toBe(87.5);
  });

  it("does not treat eligibility as an observed healthy runtime", () => {
    expect(
      getStatusInfo({
        healthy: null,
        status: "unknown",
        health_basis: "eligibility",
        runtime_observed: false,
      }),
    ).toEqual({ tone: "warning", label: "Não verificado" });
  });

  it("does not show a simulation as live provider health", () => {
    expect(getStatusInfo({ healthy: true, simulation: true })).toEqual({
      tone: "warning",
      label: "Simulação",
    });
  });

  it("does not mistake the manager's zero-call default for a successful health check", () => {
    expect(
      getStatusInfo({ healthy: true, success_rate: 1, request_count: 0, last_check: 0 }),
    ).toEqual({ tone: "warning", label: "Não verificado" });
  });

  it("allows a successful status only after a runtime observation", () => {
    expect(
      getStatusInfo({ healthy: true, request_count: 1, success_rate: 1, last_check: 123 }),
    ).toEqual({ tone: "success", label: "Saudável" });
  });
});
