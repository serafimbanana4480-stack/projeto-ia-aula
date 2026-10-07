import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdvancedModePanel from "../../../components/chat/AdvancedModeSelector";
import { useAdvancedModeStore } from "../../../stores/advancedModeStore";

vi.mock("../../../components/infinity/InfinitySuiteWorkspace", () => ({ InfinitySuiteWorkspace: () => <p>Suite workspace</p> }));

describe("Infinity suite dialog", () => {
  beforeEach(() => useAdvancedModeStore.setState({ loadModes: vi.fn().mockResolvedValue(undefined), activeModeIds: [] }));

  it("renders a labelled dialog in a portal and restores focus when Escape closes it", () => {
    const { container } = render(<AdvancedModePanel />);
    const trigger = screen.getByRole("button", { name: "Abrir Infinity Suite" });
    trigger.focus(); fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Infinity Suite" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(container.contains(dialog)).toBe(false);
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe("");
  });
});
