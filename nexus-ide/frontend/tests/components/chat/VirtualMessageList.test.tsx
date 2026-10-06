import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VirtualMessageList from "../../../components/chat/VirtualMessageList";

interface Row {
  id: string;
}

function rows(count: number): Row[] {
  return Array.from({ length: count }, (_, index) => ({ id: `row-${index}` }));
}

function renderRow(row: Row) {
  return <div data-row="true" key={row.id}>{row.id}</div>;
}

describe("VirtualMessageList long history window", () => {
  it("keeps a 10,000-message snapshot bounded and pages older rows without duplicates", () => {
    const { container } = render(
      <VirtualMessageList messages={rows(10_000)} renderItem={renderRow} initialLimit={50} resetKey="large-session" />,
    );

    const renderedRows = () => Array.from(container.querySelectorAll<HTMLElement>("[data-row]"));
    expect(renderedRows()).toHaveLength(50);
    expect(renderedRows()[0].textContent).toBe("row-9950");
    expect(renderedRows()[49].textContent).toBe("row-9999");

    fireEvent.click(screen.getByRole("button", { name: /Carregar mais/ }));
    expect(renderedRows()).toHaveLength(100);
    expect(renderedRows()[0].textContent).toBe("row-9900");
    expect(new Set(renderedRows().map((row) => row.textContent)).size).toBe(100);

    fireEvent.click(screen.getByRole("button", { name: /Carregar mais/ }));
    expect(renderedRows()).toHaveLength(150);
    expect(renderedRows()[0].textContent).toBe("row-9850");
    expect(renderedRows()[149].textContent).toBe("row-9999");
    expect(new Set(renderedRows().map((row) => row.textContent)).size).toBe(150);
  });

  it("resets its expanded window when a replacement snapshot arrives", () => {
    const messages = rows(120);
    const { rerender } = render(
      <VirtualMessageList
        messages={messages}
        renderItem={renderRow}
        initialLimit={50}
        resetKey="session-1:snapshot-1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Carregar mais/ }));
    expect(screen.getByText("row-20")).toBeTruthy();

    rerender(
      <VirtualMessageList
        messages={messages}
        renderItem={renderRow}
        initialLimit={50}
        resetKey="session-1:snapshot-2"
      />,
    );

    expect(screen.queryByText("row-20")).toBeNull();
    expect(screen.getByText("row-70")).toBeTruthy();
    expect(screen.getByText("row-119")).toBeTruthy();
  });

  it("keeps the visible scroll anchor in place when revealing older rows", () => {
    let scrollTop = 400;
    const { container } = render(
      <div data-testid="scroll-container" style={{ overflowY: "auto", height: 300 }}>
        <VirtualMessageList
          messages={rows(120)}
          renderItem={renderRow}
          initialLimit={50}
          resetKey="session-1:snapshot-1"
        />
      </div>,
    );

    const scrollContainer = screen.getByTestId("scroll-container");
    Object.defineProperty(scrollContainer, "clientHeight", { configurable: true, value: 300 });
    Object.defineProperty(scrollContainer, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => { scrollTop = value; },
    });
    Object.defineProperty(scrollContainer, "scrollHeight", {
      configurable: true,
      get: () => 1_000 + container.querySelectorAll("[data-row]").length * 10,
    });

    fireEvent.click(screen.getByRole("button", { name: /Carregar mais/ }));

    expect(container.querySelectorAll("[data-row]")).toHaveLength(100);
    expect(scrollTop).toBe(900);
  });
});
