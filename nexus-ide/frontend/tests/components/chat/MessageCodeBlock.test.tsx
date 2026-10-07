import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MessageCodeBlock from "../../../components/chat/MessageCodeBlock";

describe("MessageCodeBlock", () => {
  it("renderiza o realce de sintaxe quando o módulo é carregado", () => {
    const { container } = render(
      <MessageCodeBlock language="typescript" code="const answer = 42;" theme="dark" />,
    );

    expect(container.textContent).toContain("const answer = 42;");
    expect(container.querySelector(".token")).not.toBeNull();
  });

  it("reserva espaço acima do código para a barra de linguagem e cópia", () => {
    const { container } = render(
      <MessageCodeBlock language="typescript" code="const answer = 42;" theme="dark" />,
    );
    const styledBlock = Array.from(container.querySelectorAll<HTMLElement>("[style]"))
      .find((element) => element.style.paddingTop);

    expect(styledBlock?.style.paddingTop).toBe("2.5rem");
  });
});
