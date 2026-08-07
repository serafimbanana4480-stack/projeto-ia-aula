import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import QualityGateStatus from "../../../components/mission-control/QualityGateStatus";
import { useMissionStore } from "../../../stores/missionStore";

describe("QualityGateStatus", () => {
  it("renders a clear empty state when no gate data is available", () => {
    useMissionStore.setState({ qualityGates: [] });
    render(<QualityGateStatus />);
    expect(screen.getByText("Quality Gates")).toBeDefined();
    expect(screen.getByText("Sem gates de qualidade disponíveis")).toBeDefined();
    expect(screen.getByText("Aguardando eventos do backend")).toBeDefined();
  });

  it("renders gate values when provided", () => {
    useMissionStore.setState({
      qualityGates: [
        { name: "tests", label: "Testes", status: "pass", value: "94%", threshold: "90%" },
        { name: "security", label: "Segurança", status: "fail", value: "2", threshold: "0" },
      ],
    });
    render(<QualityGateStatus />);
    expect(screen.getByText("94%")).toBeDefined();
    expect(screen.getByText("2")).toBeDefined();
  });
});
