/**
 * `MessageBubble` is the only place in the app where `react-markdown`,
 * `react-syntax-highlighter` and `sanitizeAssistantContent` meet, and it had
 * ZERO tests. That makes this file the guard for the whole assistant-output
 * trust boundary: everything the model, a tool or a replayed journal can put
 * in `message.content` reaches the DOM through here.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import MessageBubble from "../../../components/chat/MessageBubble";
import type { ChatMessage } from "../../../lib/types";
import { useThemeStore } from "../../../stores/themeStore";

function assistant(content: string, overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    agent: "NEXUS",
    content,
    timestamp: new Date().toISOString(),
    ...overrides,
  };
}

function user(content: string, overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "u1",
    role: "user",
    content,
    timestamp: new Date().toISOString(),
    ...overrides,
  };
}

describe("MessageBubble — markdown rendering", () => {
  it("renderiza markdown como HTML estruturado, não como texto", () => {
    const { container } = render(
      <MessageBubble message={assistant("**negrito** e *itálico*")} />,
    );

    expect(container.querySelector("strong")?.textContent).toBe("negrito");
    expect(container.querySelector("em")?.textContent).toBe("itálico");
  });

  it("renderiza listas ordenadas e não ordenadas com a classe de estilo", () => {
    const { container } = render(
      <MessageBubble message={assistant("1. primeiro\n2. segundo\n\n- a\n- b")} />,
    );

    const ol = container.querySelector("ol");
    const ul = container.querySelector("ul");
    expect(ol).not.toBeNull();
    expect(ul).not.toBeNull();
    expect(ol?.className).toContain("list-decimal");
    expect(ul?.className).toContain("list-disc");
    expect(ol?.querySelectorAll("li")).toHaveLength(2);
    expect(ul?.querySelectorAll("li")).toHaveLength(2);
  });

  it("renderiza um bloco de código com realce e cópia, e identifica a linguagem", async () => {
    const { container } = render(
      <MessageBubble
        message={assistant("```python\nprint('olá')\n```")}
      />,
    );

    await screen.findByText("python");
    // The language badge is part of the fenced-code affordance.
    expect(screen.getByText("python")).toBeTruthy();
    // `SyntaxHighlighter` renders the tokenised code into a <pre>.
    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.textContent).toContain("print");
    expect(screen.getByRole("button", { name: "Copiar bloco de código" })).toBeTruthy();
  });

  it("trata código inline sem lhe dar o treatment de bloco", () => {
    const { container } = render(
      <MessageBubble message={assistant("usa `npm test` antes de fechar")} />,
    );

    const codes = container.querySelectorAll("code");
    expect(codes).toHaveLength(1);
    expect(codes[0].textContent).toBe("npm test");
    // No fenced-block chrome for an inline span.
    expect(screen.queryByText("Copiar")).toBeNull();
  });

  it("não renderiza o fallback de texto puro quando há conteúdo", () => {
    const { container } = render(<MessageBubble message={assistant("olá")} />);
    // The `typeof ReactMarkdown !== "undefined"` ternary has a plain-text
    // branch; with markdown available it must not be taken.
    expect(container.querySelector(".whitespace-pre-wrap")).toBeNull();
    expect(container.textContent).toContain("olá");
  });

  it("remove códigos ANSI antes de handedos ao renderer", () => {
    const { container } = render(
      <MessageBubble message={assistant("\u001b[31mvermelho\u001b[0m")} />,
    );
    // ESC would render as a control character in the DOM.
    expect(container.textContent).not.toContain("\u001b");
    expect(container.textContent).toContain("vermelho");
  });

  it("separa atividade da resposta e mostra apenas os ficheiros reportados pelo runtime", () => {
    const message = assistant("Resposta pronta.", {
      metadata: { changedFiles: ["src/real.ts", "", "docs/real.md"] },
      steps: [
        {
          seq: 1,
          kind: "tool_started",
          label: "a usar ferramenta",
          target: "read_file",
          verb: "tool",
          status: "success",
          icon: "wrench",
        },
      ],
    });
    render(<MessageBubble message={message} />);
    const response = screen.getByTestId("assistant-response");
    const activity = screen.getByTestId("run-timeline-toggle");
    const artifact = screen.getByTestId("changed-files-artifact");

    expect(response.textContent).toContain("Resposta pronta.");
    expect(response.contains(activity)).toBe(false);
    expect(response.contains(artifact)).toBe(false);
    expect(artifact.textContent).toContain("(2)");
    expect(artifact.textContent).toContain("src/real.ts");
    expect(artifact.textContent).toContain("docs/real.md");
    expect(artifact.textContent).not.toContain("Ficheiros alterados (3)");
  });

  it("mantém a mensagem do utilizador numa superfície neutra", () => {
    const { container } = render(<MessageBubble message={user("Olá")} />);
    const bubble = container.querySelector(".bg-nexus-elevated");

    expect(bubble).not.toBeNull();
    expect(bubble?.className).not.toContain("bg-gradient-to-br");
    expect(bubble?.className).not.toContain("hover:scale");
  });
});

describe("MessageBubble — XSS / transport-markup neutralisation", () => {
  it("não executa HTML nem <script> vindos do assistente", () => {
    const { container } = render(
      <MessageBubble
        message={assistant(
          "antes <script>window.__pwned = true</script> depois",
        )}
      />,
    );

    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined();
    expect(container.querySelector("script")).toBeNull();
    // `react-markdown` does not pass raw HTML through without a plugin, so the
    // tag shows up as inert text rather than as an element.
    expect(container.textContent).toContain("antes");
    expect(container.textContent).toContain("depois");
  });

  it("não deixa um atributo de handler sobreviver como elemento", () => {
    const { container } = render(
      <MessageBubble
        message={assistant('<img src="x" onerror="window.__pwned = true">')}
      />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined();
  });

  it("não deixa markup de ferramenta/transporto chegar ao texto visível", () => {
    // This is the bug class the swarm lane hit too: `<thinking>`/`<tool_call>`
    // are transport, and `sanitizeAssistantContent` is the only thing standing
    // between them and the operator's eyes.
    const { container } = render(
      <MessageBubble
        message={assistant(
          "A resposta é 42.\n<tool_call>{\"name\": \"read_file\"}</tool_call>",
        )}
      />,
    );

    expect(container.textContent).toContain("A resposta é 42.");
    expect(container.textContent).not.toContain("<tool_call>");
    expect(container.textContent).not.toContain("read_file");
  });

  it("remove um bloco <thinking> mas mantém o texto lá dentro", () => {
    const { container } = render(
      <MessageBubble
        message={assistant("<thinking>Primeiro leio o ficheiro.</thinking>Concluído.")}
      />,
    );

    expect(container.textContent).not.toContain("<thinking>");
    expect(container.textContent).not.toContain("</thinking>");
    expect(container.textContent).toContain("Primeiro leio o ficheiro.");
    expect(container.textContent).toContain("Concluído.");
  });

  it("NÃO sanitiza a mensagem do utilizador", () => {
    // The user's own text is theirs: sanitising it would silently rewrite what
    // they typed, and a user asking about a `<script>` tag must see their tag.
    const { container } = render(
      <MessageBubble message={user("como faço <script>alert(1)</script>?")} />,
    );

    expect(container.textContent).toContain("<script>alert(1)</script>");
  });
});

describe("MessageBubble — agent attribution", () => {
  it("mostra o nome do agente e a inicial no avatar", () => {
    render(<MessageBubble message={assistant("pronto", { agent: "CODER" })} />);

    // The header label and the avatar initial both carry the agent.
    expect(screen.getAllByText("CODER").length).toBeGreaterThan(0);
  });

  it("cai para NEXUS quando a mensagem não tem agente", () => {
    render(<MessageBubble message={assistant("pronto", { agent: undefined })} />);
    expect(screen.getAllByText("NEXUS").length).toBeGreaterThan(0);
  });

  it("marca a mensagem como viva enquanto transmite", () => {
    render(<MessageBubble message={assistant("a meio")} isStreaming />);
    expect(screen.getByText("ao vivo")).toBeTruthy();
  });

  it("rotula a mensagem do utilizador como 'Você' e não como agente", () => {
    render(<MessageBubble message={user("olá")} />);
    expect(screen.getByText("Você")).toBeTruthy();
  });
});

describe("MessageBubble — streaming placeholder and actions", () => {
  it("mostra 'A pensar...' enquanto não há nada para mostrar", () => {
    render(<MessageBubble message={assistant("")} isStreaming />);
    expect(screen.getByText("A pensar...")).toBeTruthy();
  });

  it("esconde o placeholder quando a mensagem já tem atividade", () => {
    render(
      <MessageBubble
        message={assistant("", {
          activities: [
            {
              id: "a1",
              kind: "status",
              title: "A avançar",
              status: "running",
              timestamp: "2026-01-01T00:00:00Z",
              data: {},
            },
          ],
        })}
        isStreaming
      />,
    );
    expect(screen.queryByText("A pensar...")).toBeNull();
  });

  it("esconde o placeholder quando há raciocínio a transmitir", () => {
    render(
      <MessageBubble
        message={assistant("", { thinking: "a definir a abordagem" })}
        isStreaming
      />,
    );
    expect(screen.queryByText("A pensar...")).toBeNull();
  });

  it("oferece reenviar quando a mensagem é um erro recuperável", () => {
    const onRetry = vi.fn();
    render(
      <MessageBubble
        message={assistant("O servidor não respondeu.", {
          metadata: { kind: "error", canRetry: true, prompt: "a pergunta original" },
        })}
        onRetry={onRetry}
      />,
    );

    fireEvent.click(screen.getByText("Tentar novamente"));
    expect(onRetry).toHaveBeenCalledWith("a pergunta original");
  });

  it("não oferece reenviar quando o erro não é recuperável", () => {
    render(
      <MessageBubble
        message={assistant("falhou", { metadata: { kind: "error", canRetry: false } })}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByText("Tentar novamente")).toBeNull();
  });

  it("identifica uma execução interrompida separadamente de uma falha", () => {
    render(
      <MessageBubble
        message={assistant("O provider interrompeu a execução.", {
          metadata: { kind: "error", outcome: "interrupted", canRetry: true },
        })}
      />,
    );

    expect(screen.getByText("Interrompido")).toBeTruthy();
    expect(screen.queryByText("Erro", { exact: true })).toBeNull();
  });

  it("regenera a resposta pelo id da mensagem", () => {
    const onRegenerate = vi.fn();
    render(
      <MessageBubble
        message={assistant("primeira versão")}
        onRegenerate={onRegenerate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Regenerar resposta" }));
    expect(onRegenerate).toHaveBeenCalledWith("m1");
  });

  it("edita a mensagem do utilizador e entrega o novo texto", () => {
    const onEdit = vi.fn();
    render(<MessageBubble message={user("versão original")} onEdit={onEdit} />);

    fireEvent.click(screen.getByRole("button", { name: "Editar mensagem" }));
    const textarea = screen.getByDisplayValue("versão original") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "  versão corrigida  " } });
    fireEvent.click(screen.getByText("Guardar e regenerar"));

    expect(onEdit).toHaveBeenCalledWith("u1", "versão corrigida");
  });

  it("não entrega uma edição que não mudou nada", () => {
    const onEdit = vi.fn();
    render(<MessageBubble message={user("igual")} onEdit={onEdit} />);

    fireEvent.click(screen.getByTitle("Editar mensagem"));
    fireEvent.click(screen.getByText("Guardar e regenerar"));

    expect(onEdit).not.toHaveBeenCalled();
  });
});

describe("MessageBubble — clipboard", () => {
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    writeText.mockClear();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
  });

  afterEach(() => {
    useThemeStore.setState({ theme: "dark" });
  });

  it("copia a mensagem e confirma visualmente", async () => {
    render(<MessageBubble message={assistant("conteúdo a copiar")} />);

    fireEvent.click(screen.getByTitle("Copiar mensagem"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("conteúdo a copiar"));
  });

  it("copia o código de um bloco fenced", async () => {
    render(<MessageBubble message={assistant("```js\nconst a = 1;\n```")} />);

    await screen.findByRole("button", { name: "Copiar bloco de código" });
    fireEvent.click(screen.getByTitle("Copiar código"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("const a = 1;"));
  });

  it("não rebenta quando a clipboard do browser não existe", () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    render(<MessageBubble message={assistant("sem clipboard")} />);

    // The empty catch must swallow the rejection instead of unmounting the
    // whole chat surface.
    expect(() => fireEvent.click(screen.getByTitle("Copiar mensagem"))).not.toThrow();
  });
});
