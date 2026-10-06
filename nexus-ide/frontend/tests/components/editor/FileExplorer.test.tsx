import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import FileExplorer from "../../../components/editor/FileExplorer";
import type { FileTreeEntry } from "../../../lib/types";

/**
 * Real render tests. This file used to be an `expect(true).toBe(true)` stub
 * that imported nothing, so FileExplorer.tsx (127 lines of tree rendering,
 * expand/collapse and click-to-select) had zero coverage while the suite
 * reported green.
 */

function file(path: string, name: string): FileTreeEntry {
  return { path, name, type: "file", size: 10 };
}

function dir(path: string, name: string, children: FileTreeEntry[]): FileTreeEntry {
  return { path, name, type: "directory", size: 0, children };
}

const TREE: FileTreeEntry[] = [
  dir("src", "src", [
    file("src/app.tsx", "app.tsx"),
    dir("src/lib", "lib", [file("src/lib/api.ts", "api.ts")]),
  ]),
  file("README.md", "README.md"),
];

function renderExplorer(overrides: Partial<{
  tree: FileTreeEntry[];
  activePath: string;
  loading: boolean;
  onSelectFile: (path: string) => void;
}> = {}) {
  const onSelectFile = vi.fn();
  const props = {
    tree: TREE,
    activePath: "",
    loading: false,
    onSelectFile,
    ...overrides,
  };
  return { ...render(<FileExplorer {...props} />), onSelectFile, props };
}

describe("FileExplorer", () => {
  it("mostra o estado de carregamento e não a árvore", () => {
    renderExplorer({ loading: true });

    expect(screen.getByText("Loading files...")).toBeTruthy();
    expect(screen.queryByText("README.md")).toBeNull();
  });

  it("mostra o estado vazio quando não há ficheiros", () => {
    renderExplorer({ tree: [] });

    expect(screen.getByText("No files found.")).toBeTruthy();
  });

  it("renderiza a raiz da árvore", () => {
    renderExplorer();

    // depth 0 directories start expanded (FileExplorer.tsx:25 -> depth < 1)
    expect(screen.getByText("src")).toBeTruthy();
    expect(screen.getByText("README.md")).toBeTruthy();
  });

  it("renderiza os filhos de um directório expandido", () => {
    renderExplorer();

    expect(screen.getByText("app.tsx")).toBeTruthy();
    expect(screen.getByText("lib")).toBeTruthy();
    // 'lib' is at depth 1, so it starts collapsed and its child is not shown.
    expect(screen.queryByText("api.ts")).toBeNull();
  });

  it("recolhe e expande um directório ao clicar", () => {
    renderExplorer();

    // depth 0 is expanded by default, so its child is visible.
    expect(screen.getByText("app.tsx")).toBeTruthy();
    fireEvent.click(screen.getByText("src"));
    expect(screen.queryByText("app.tsx")).toBeNull();

    fireEvent.click(screen.getByText("src"));
    expect(screen.getByText("app.tsx")).toBeTruthy();
  });

  it("expande um directório de segundo nível e mostra o seu filho", () => {
    renderExplorer();

    fireEvent.click(screen.getByText("lib"));

    expect(screen.getByText("api.ts")).toBeTruthy();
  });

  it("chama onSelectFile com o path ao clicar num ficheiro", () => {
    const { onSelectFile } = renderExplorer();

    fireEvent.click(screen.getByText("README.md"));

    expect(onSelectFile).toHaveBeenCalledTimes(1);
    expect(onSelectFile).toHaveBeenCalledWith("README.md");
  });

  it("chama onSelectFile com o path completo de um ficheiro aninhado", () => {
    const { onSelectFile } = renderExplorer();

    fireEvent.click(screen.getByText("app.tsx"));

    expect(onSelectFile).toHaveBeenCalledWith("src/app.tsx");
  });

  it("marca o ficheiro activo com a classe de destaque", () => {
    renderExplorer({ activePath: "README.md" });

    const active = screen.getByText("README.md").closest("button");
    const inactive = screen.getByText("app.tsx").closest("button");

    expect(active?.className).toContain("bg-nexus-accent");
    expect(inactive?.className).not.toContain("bg-nexus-accent");
  });

  it("não chama onSelectFile ao clicar no directório", () => {
    const { onSelectFile } = renderExplorer();

    fireEvent.click(screen.getByText("src"));

    expect(onSelectFile).not.toHaveBeenCalled();
  });

  it("não rebenta com um directório sem filhos", () => {
    renderExplorer({ tree: [dir("empty", "empty", [])] });

    expect(screen.getByText("empty")).toBeTruthy();
  });
});
