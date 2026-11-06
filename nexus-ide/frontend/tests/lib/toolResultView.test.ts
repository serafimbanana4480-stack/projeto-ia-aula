import { describe, expect, it } from "vitest";

import { classifyToolResult } from "../../lib/toolResultView";

describe("classifyToolResult", () => {
  it("trata uma série temporal com pelo menos dois pontos como gráfico", () => {
    const view = classifyToolResult({
      unit: "ms",
      points: [
        { timestamp: "2026-01-01T00:00:00Z", value: 12 },
        { timestamp: "2026-01-01T00:01:00Z", value: 18 },
        { timestamp: "2026-01-01T00:02:00Z", value: 15 },
      ],
    });

    expect(view.kind).toBe("series");
    if (view.kind !== "series") return;
    expect(view.points).toEqual([
      { x: "2026-01-01T00:00:00Z", y: 12 },
      { x: "2026-01-01T00:01:00Z", y: 18 },
      { x: "2026-01-01T00:02:00Z", y: 15 },
    ]);
    expect(view.unit).toBe("ms");
    expect(view.summary).toBe("3 pontos, de 2026-01-01T00:00:00Z a 2026-01-01T00:02:00Z (ms)");
  });

  it("trata uma lista {x,y} numérica com dois pontos como gráfico, sem inventar unidade", () => {
    const view = classifyToolResult([
      { x: 1, y: 4 },
      { x: 2, y: 9 },
    ]);

    expect(view).toMatchObject({
      kind: "series",
      unit: undefined,
      summary: "2 pontos, de 1 a 2",
      points: [
        { x: 1, y: 4 },
        { x: 2, y: 9 },
      ],
    });
  });

  it("não desenha gráfico com menos de dois pontos", () => {
    expect(classifyToolResult([{ x: 1, y: 4 }])).toEqual({ kind: "none" });
    expect(classifyToolResult({ points: [] })).toEqual({ kind: "none" });
    expect(classifyToolResult({ data: [{ x: 1, y: 2 }] })).toEqual({ kind: "none" });
  });

  it("não inventa números em falta nem converte texto em valor", () => {
    expect(
      classifyToolResult([
        { x: 1, y: 2 },
        { x: 2, y: null },
      ]),
    ).toMatchObject({
      kind: "table",
      columns: ["x", "y"],
      rows: [
        { x: 1, y: 2 },
        { x: 2, y: null },
      ],
    });

    expect(
      classifyToolResult([
        { x: 1, y: "2" },
        { x: 2, y: "9" },
      ]).kind,
    ).toBe("table");

    const holed = classifyToolResult([
      { x: 1, y: 2 },
      { x: 2 },
    ]);
    expect(holed.kind).toBe("table");
    if (holed.kind !== "table") return;
    expect(holed.columns).toEqual(["x"]);
    expect(holed.rows).toEqual([{ x: 1 }, { x: 2 }]);
    expect(JSON.stringify(holed)).not.toContain('"y"');
  });

  it("só inclui colunas presentes em todas as linhas, com valores escalares", () => {
    const view = classifyToolResult({
      rows: [
        { nome: "alpha", valor: 1, extra: { nested: true } },
        { nome: "beta", valor: 3 },
        { nome: "gamma", valor: null, nota: "só aqui" },
      ],
    });

    expect(view).toEqual({
      kind: "table",
      columns: ["nome", "valor"],
      rows: [
        { nome: "alpha", valor: 1 },
        { nome: "beta", valor: 3 },
        { nome: "gamma", valor: null },
      ],
    });
  });

  it("deixa texto, listas soltas e objetos sem série ou tabela de fora", () => {
    expect(classifyToolResult("conteúdo do ficheiro")).toEqual({ kind: "none" });
    expect(classifyToolResult([1, 2, 3])).toEqual({ kind: "none" });
    expect(classifyToolResult({ linhas: 12 })).toEqual({ kind: "none" });
    expect(classifyToolResult({ sources: [{ url: "https://example.org" }] })).toEqual({ kind: "none" });
    expect(
      classifyToolResult({
        memories: [
          { type: "project", project_id: "nexus" },
          { type: "session" },
        ],
      }),
    ).toEqual({ kind: "none" });
  });

  it("lê a série dentro do envelope result sem promover outra lista", () => {
    const view = classifyToolResult({
      ok: true,
      result: {
        points: [
          { x: 0, y: 1 },
          { x: 1, y: 2 },
        ],
      },
    });
    expect(view.kind).toBe("series");
  });
});
