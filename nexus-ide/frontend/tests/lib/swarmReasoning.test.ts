/**
 * `lib/swarmReasoning.ts` is what feeds the SWARM page's reasoning block.
 * Two properties matter and neither is obvious from the component: the text
 * must come only from what the run actually produced (never invented), and
 * `<thinking>` markup must never reach the operator's screen — the new swarm
 * lane does not strip it, only the legacy lane does.
 */
import { describe, expect, it } from "vitest";

import { sanitizeSwarmAnswer, swarmReasoningText } from "../../lib/swarmReasoning";

describe("swarmReasoningText", () => {
  it("monta o razo das decisões do coordenador", () => {
    const text = swarmReasoningText({
      decisions: [
        {
          decision_id: "d1",
          title: "Adotar SQLite",
          rationale: "É single-writer e não exige um servidor extra.",
          decided_by: "ARCHITECT",
          confidence: 0.9,
        },
      ],
    });

    expect(text).toContain("Adotar SQLite");
    expect(text).toContain("É single-writer");
    // The ADR id and the confidence are not reasoning; they live in the Trace
    // tab already.
    expect(text).not.toContain("d1");
    expect(text).not.toContain("0.9");
  });

  it("prefere a rationale da proposta à sua descrição", () => {
    const text = swarmReasoningText({
      proposals: [
        {
          proposal_id: "p1",
          title: "Extrair o store",
          description: "Descrição alternativa.",
          rationale: "Porque o módulo tem dois consumidores.",
        },
      ],
    });

    expect(text).toContain("Porque o módulo tem dois consumidores.");
    expect(text).not.toContain("Descrição alternativa.");
  });

  it("usa a descrição quando a proposta não tem rationale", () => {
    const text = swarmReasoningText({
      proposals: [{ proposal_id: "p1", title: "Sem razão", description: "Só isto." }],
    });
    expect(text).toContain("Só isto.");
  });

  it("marca o sentido da revisão do reviewer", () => {
    const text = swarmReasoningText({
      reviews: [
        { review_id: "r1", passed: true, summary: "Cobre o caso limite." },
        { review_id: "r2", passed: false, summary: "Falta o teste de concorrência." },
      ],
    });

    expect(text).toContain("Revisão aprovada");
    expect(text).toContain("Revisão rejeitada");
  });

  it("respeita a ordem em que a execução produziu as peças", () => {
    const text = swarmReasoningText({
      decisions: [{ title: "D", rationale: "porquê D" }],
      proposals: [{ title: "P", rationale: "porquê P" }],
      reviews: [{ passed: true, summary: "veredito" }],
    });

    expect(text.indexOf("porquê D")).toBeLessThan(text.indexOf("porquê P"));
    expect(text.indexOf("porquê P")).toBeLessThan(text.indexOf("veredito"));
  });

  it("NÃO inventa raciocínio: sem peças estruturadas cita apenas a resposta", () => {
    // A run with no decisions/proposals/reviews reasoned nothing the UI can
    // attribute, so the honest fallback is the answer itself — and if there is
    // no answer either, nothing at all.
    const fromAnswer = swarmReasoningText({ final_answer: "O cache está em Redis." });
    expect(fromAnswer).toBe("O cache está em Redis.");

    expect(swarmReasoningText({})).toBe("");
    expect(swarmReasoningText({ decisions: [], proposals: [], reviews: [] })).toBe("");
  });

  it("salta entradas vazias em vez de deixar títulos órfãos", () => {
    const text = swarmReasoningText({
      decisions: [{ title: "Só o título" }, { title: "Com texto", rationale: "porque sim" }],
      reviews: [{ passed: true }],
    });

    expect(text).toContain("Com texto");
    expect(text).not.toContain("Só o título");
    expect(text).not.toContain("Revisão");
  });

  it("aceita um título ausente sem deitar o razo fora", () => {
    const text = swarmReasoningText({ decisions: [{ rationale: "sem título nenhum" }] });
    expect(text).toContain("sem título nenhum");
  });

  it("remove a marcação <thinking> do razo, mantendo o texto", () => {
    // `backend/swarm/core/orchestrator.py:589` only sets
    // `enable_thinking=False`; it never strips the tags. Only the LEGACY lane
    // (`backend/orchestrator/swarm.py:958`) calls `_strip_thinking_markup`.
    const text = swarmReasoningText({
      decisions: [
        { title: "D", rationale: "<thinking>Vou ler o schema primeiro.</thinking>Escolho B." },
      ],
    });

    expect(text).not.toContain("<thinking>");
    expect(text).not.toContain("</thinking>");
    expect(text).toContain("Vou ler o schema primeiro.");
    expect(text).toContain("Escolho B.");
  });

  it("devolve vazio para payloads inúteis em vez de rebentar", () => {
    for (const junk of [null, undefined, 0, "texto", [], true, { decisions: "não é uma lista" }]) {
      expect(swarmReasoningText(junk)).toBe("");
    }
  });

  it("tolera uma lista com entradas mal formadas", () => {
    const text = swarmReasoningText({
      decisions: [null, 42, { title: "Bom", rationale: "isto conta" }] as never,
    });
    expect(text).toBe("**Bom** — isto conta");
  });
});

describe("sanitizeSwarmAnswer", () => {
  it("devolve a resposta limpa", () => {
    expect(sanitizeSwarmAnswer({ final_answer: "pronto." })).toBe("pronto.");
  });

  it("remove <thinking>, <reasoning> e <scratchpad>", () => {
    for (const tag of ["thinking", "reasoning", "scratchpad", "think"]) {
      const answer = sanitizeSwarmAnswer({
        final_answer: `<${tag}>transporte</${tag}> conteúdo`,
      });
      expect(answer).not.toContain(`<${tag}>`);
      expect(answer).toContain("conteúdo");
    }
  });

  it("remove um payload de ferramenta em JSON puro que o modelo despejou", () => {
    const answer = sanitizeSwarmAnswer({
      final_answer:
        'Aqui está.\n{"name": "write_file", "arguments": {"path": "x.py"}}\nFim.',
    });

    expect(answer).toContain("Aqui está.");
    expect(answer).toContain("Fim.");
    expect(answer).not.toContain("write_file");
  });

  it("devolve vazio quando não há resposta", () => {
    expect(sanitizeSwarmAnswer({})).toBe("");
    expect(sanitizeSwarmAnswer(null)).toBe("");
    expect(sanitizeSwarmAnswer({ final_answer: "   \n\n  " })).toBe("");
  });

  it("não deixa escapar a marcação para o texto do chat", () => {
    // The swarm page renders `insertText` inside a `whitespace-pre-wrap` div,
    // i.e. as plain text — so an unstripped `<thinking>` would be shown to the
    // user verbatim.
    const answer = sanitizeSwarmAnswer({
      final_answer: "<thinking>passo 1</thinking>\n<thinking>passo 2</thinking>Resposta",
    });
    expect(answer).not.toMatch(/<\/?thinking>/);
    expect(answer).toContain("passo 1");
    expect(answer).toContain("Resposta");
  });
});
