import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import SettingsPage from "../../app/settings/page";
import { getSettings, saveSettings } from "../../lib/api";

vi.mock("../../components/layout/AppShell", () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("../../lib/api", () => ({
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
}));

describe("Brave search credential settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(getSettings).mockResolvedValue({
      brave_api_key: "ABCD****WXYZ",
    });
    vi.mocked(saveSettings).mockResolvedValue({ status: "saved" });
  });

  it("keeps masked credentials out of the field and clears a new key after save", async () => {
    render(<SettingsPage />);

    const input = await screen.findByLabelText("Brave Search API Key") as HTMLInputElement;
    expect(input.value).toBe("");
    expect(screen.getByText(/deixa o campo vazio para a manter/i)).toBeTruthy();

    fireEvent.change(input, { target: { value: "brave-test-key-1234" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() => expect(input.value).toBe(""));
    expect(saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ brave_api_key: "brave-test-key-1234" }),
    );
    expect(localStorage.getItem("nexus_settings")).toBeNull();
  });

  it("never copies the Brave key into local browser settings on save failure", async () => {
    vi.mocked(saveSettings).mockRejectedValue(new Error("backend offline"));
    render(<SettingsPage />);

    const input = await screen.findByLabelText("Brave Search API Key");
    fireEvent.change(input, { target: { value: "brave-test-key-1234" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await screen.findByText(/guardadas apenas neste navegador/i);
    expect(localStorage.getItem("nexus_settings")).not.toContain("brave-test-key-1234");
  });
});
