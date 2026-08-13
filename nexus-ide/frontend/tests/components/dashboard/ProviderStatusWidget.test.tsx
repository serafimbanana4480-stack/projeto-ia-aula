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
});
