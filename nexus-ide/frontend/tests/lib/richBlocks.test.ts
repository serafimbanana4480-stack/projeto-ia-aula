import { describe, expect, it } from "vitest";

import { parseRichBlock, promoteMarkdownTables } from "../../lib/richBlocks";

describe("parseRichBlock", () => {
  it("aceita cartões, gráfico, estado e fontes http", () => {
    expect(
      parseRichBlock("stats", '{"items":[{"value":"86","label":"Testes"}]}'),
    ).toEqual({ kind: "stats", items: [{ value: "86", label: "Testes" }] });

    const chart = parseRichBlock(
      "nexus-chart",
      '{"title":"Investimento","bars":[{"label":"EUA","value":320}]}',
    );
    expect(chart?.kind).toBe("chart");

    expect(
      parseRichBlock(
        "status",
        '{"rows":[{"name":"WSL","state":"ok","label":"Validada"}]}',
      )?.kind,
    ).toBe("status");

    expect(
      parseRichBlock(
        "sources",
        '{"items":[{"title":"Stanford","url":"https://hai.stanford.edu"}]}',
      )?.kind,
    ).toBe("sources");
  });

  it("rejeita linguagem normal, JSON partido, ícone desconhecido e url insegura", () => {
    expect(parseRichBlock("python", "print(1)")).toBeNull();
    expect(parseRichBlock("stats", "não json")).toBeNull();
    expect(parseRichBlock("cards", '{"items":[{"icon":"rocket","title":"X"}]}')).toBeNull();
    expect(
      parseRichBlock("sources", '{"items":[{"title":"x","url":"javascript:alert(1)"}]}'),
    ).toBeNull();
    expect(parseRichBlock("meter", '{"label":"Taxa","value":120,"max":100}')).toBeNull();
  });

  it("converte uma tabela markdown numa fence e deixa código intocado", () => {
    const promoted = promoteMarkdownTables(
      "texto\n\n| Componente | Estado |\n| --- | --- |\n| WSL | Validada |\n\n```python\n| a | b |\n```\n",
    );
    expect(promoted).toContain("```table");
    expect(promoted).toContain("Validada");
    expect(promoted).toContain("```python");
    expect(parseRichBlock("table", '{"columns":["Componente","Estado"],"rows":[["WSL","Validada"]]}')?.kind).toBe(
      "table",
    );
  });

  it("calcula a barra só a partir dos dois números escritos", () => {
    expect(parseRichBlock("meter", '{"label":"Taxa","value":97,"max":100,"parts":[]}')).toEqual({
      kind: "meter",
      label: "Taxa",
      value: 97,
      max: 100,
      parts: [],
    });
  });
});
