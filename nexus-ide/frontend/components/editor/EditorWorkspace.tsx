"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  FileCode2,
  FolderOpen,
  RefreshCw,
  Save,
  TerminalSquare,
} from "lucide-react";
import dynamic from "next/dynamic";
import FileExplorer from "./FileExplorer";
import Terminal from "./Terminal";
import {
  executeTerminalCommand,
  listFiles,
  readFile,
  writeFile,
} from "../../lib/api";
import {
  desktopExecuteCommand,
  desktopListFiles,
  desktopReadFile,
  desktopWriteFile,
  selectDesktopDirectory,
} from "../../lib/desktop";
import type { FileTreeEntry, TerminalExecutionResult } from "../../lib/types";

const MonacoEditor = dynamic(() => import("./MonacoEditor"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-nexus-muted">
      A carregar editor…
    </div>
  ),
});

function findFirstFile(nodes: FileTreeEntry[]): FileTreeEntry | null {
  for (const node of nodes) {
    if (node.type === "file") return node;
    if (node.children?.length) {
      const nested = findFirstFile(node.children);
      if (nested) return nested;
    }
  }
  return null;
}

function inferLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "ts":
    case "tsx":
      return "typescript";
    case "js":
    case "jsx":
      return "javascript";
    case "py":
      return "python";
    case "json":
      return "json";
    case "md":
      return "markdown";
    case "css":
      return "css";
    case "html":
      return "html";
    case "sh":
      return "shell";
    default:
      return "plaintext";
  }
}

export default function EditorWorkspace() {
  const [tree, setTree] = useState<FileTreeEntry[]>([]);
  const [workspaceRoot, setWorkspaceRoot] = useState<string>(".");
  const [activePath, setActivePath] = useState<string>("");
  const [content, setContent] = useState<string>("");
  const [loadingTree, setLoadingTree] = useState(true);
  const [loadingFile, setLoadingFile] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [command, setCommand] = useState("npm test");
  const [running, setRunning] = useState(false);
  const [terminalResults, setTerminalResults] = useState<
    TerminalExecutionResult[]
  >([]);
  const [explorerCollapsed, setExplorerCollapsed] = useState(false);
  const [workspaceInput, setWorkspaceInput] = useState(".");
  const [desktopMode, setDesktopMode] = useState(false);

  const workspacePresets = useMemo(
    () => [
      { label: "Projeto inteiro", path: "." },
      { label: "Frontend", path: "frontend" },
      { label: "Backend", path: "backend" },
      { label: "Config", path: "config" },
    ],
    [],
  );

  useEffect(() => {
    setDesktopMode(
      typeof window !== "undefined" &&
        typeof window.nexusDesktop !== "undefined",
    );
  }, []);

  const loadTree = useCallback(
    async (root = workspaceRoot) => {
      setLoadingTree(true);
      setError(null);
      try {
        const entries = desktopMode
          ? await desktopListFiles(root, ".", true)
          : await listFiles(root, true, ".");
        setTree(entries);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load file tree",
        );
      } finally {
        setLoadingTree(false);
      }
    },
    [desktopMode, workspaceRoot],
  );

  const loadFile = useCallback(
    async (path: string) => {
      setLoadingFile(true);
      setError(null);
      try {
        const result = desktopMode
          ? await desktopReadFile(workspaceRoot, path)
          : await readFile(path, workspaceRoot);
        setActivePath(path);
        setContent(result.content);
        setDirty(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load file");
      } finally {
        setLoadingFile(false);
      }
    },
    [desktopMode, workspaceRoot],
  );

  useEffect(() => {
    void loadTree();
  }, [loadTree]);

  useEffect(() => {
    if (tree.length === 0) return;
    const firstFile = findFirstFile(tree);
    if (firstFile && !activePath) {
      void loadFile(firstFile.path);
      return;
    }
    if (firstFile && !content && activePath === firstFile.path) {
      void loadFile(firstFile.path);
    }
  }, [tree, content, loadFile, activePath]);

  const language = useMemo(() => inferLanguage(activePath), [activePath]);

  const handleSave = useCallback(async () => {
    if (!activePath) return;
    setSaving(true);
    setError(null);
    try {
      if (desktopMode) {
        await desktopWriteFile(workspaceRoot, activePath, content);
      } else {
        await writeFile(activePath, content, workspaceRoot);
      }
      setDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save file");
    } finally {
      setSaving(false);
    }
  }, [activePath, content, desktopMode, workspaceRoot]);

  const handleTerminalRun = useCallback(async () => {
    if (!command.trim()) return;
    setRunning(true);
    setError(null);
    try {
      const result = desktopMode
        ? await desktopExecuteCommand(workspaceRoot, command, 30)
        : await executeTerminalCommand(command, workspaceRoot, 30, "default");
      if (result) setTerminalResults((prev) => [...prev, result]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run command");
    } finally {
      setRunning(false);
    }
  }, [command, desktopMode, workspaceRoot]);

  const handleSelectDesktopFolder = useCallback(async () => {
    if (!desktopMode) {
      setError(
        "Desktop bridge not available. Open the Electron app to access any folder on the Mac.",
      );
      return;
    }

    const selected = await selectDesktopDirectory();
    if (!selected) return;

    setWorkspaceRoot(selected);
    setWorkspaceInput(selected);
    setActivePath("");
    setContent("");
    setDirty(false);
    setTerminalResults([]);
    await loadTree(selected);
  }, [desktopMode, loadTree]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 bg-nexus-bg p-3 text-gray-200">
      <div className="flex items-center justify-between rounded-lg border border-nexus-border bg-nexus-panel/60 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="rounded-md bg-nexus-accent/15 p-2 text-nexus-accent">
            <FileCode2 className="h-4 w-4" />
          </div>
          <div>
            <p className="text-sm font-semibold">Workspace de edição</p>
            <p className="text-xs text-gray-500">
              {desktopMode
                ? "Modo desktop ativo: acesso nativo a qualquer pasta do Mac"
                : "Ficheiros locais, editor controlado e terminal integrado"}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
          <span className="rounded-md border border-nexus-border bg-black/20 px-2 py-1 text-gray-300">
            {desktopMode ? "Pasta" : "Root"}: {workspaceRoot}
          </span>
          {desktopMode && (
            <button
              type="button"
              onClick={() => void handleSelectDesktopFolder()}
              className="rounded-md border border-nexus-accent bg-nexus-accent/10 px-3 py-1.5 text-gray-100 transition-colors hover:bg-nexus-accent/20"
            >
              Escolher pasta do Mac
            </button>
          )}
          <input
            value={workspaceInput}
            onChange={(e) => setWorkspaceInput(e.target.value)}
            placeholder={
              desktopMode
                ? "pasta selecionada no Mac"
                : "escreve uma pasta, ex. frontend/components"
            }
            className="min-w-[260px] rounded-md border border-nexus-border bg-black/30 px-2 py-1 text-xs text-gray-200 outline-none placeholder:text-gray-600 focus:border-nexus-accent"
          />
          <button
            type="button"
            onClick={() => {
              setWorkspaceRoot(workspaceInput.trim() || ".");
              setActivePath("");
              setContent("");
              setDirty(false);
              setTerminalResults([]);
              void loadTree(workspaceInput.trim() || ".");
            }}
            className="rounded-md border border-nexus-accent bg-nexus-accent/10 px-3 py-1.5 text-gray-100 transition-colors hover:bg-nexus-accent/20"
          >
            {desktopMode ? "Abrir pasta escrita" : "Abrir pasta"}
          </button>
          {workspacePresets.map((preset) => (
            <button
              key={preset.path}
              type="button"
              onClick={() => {
                setWorkspaceRoot(preset.path);
                setWorkspaceInput(preset.path);
                setActivePath("");
                setContent("");
                setDirty(false);
                setTerminalResults([]);
                void loadTree(preset.path);
              }}
              className={`rounded-md border px-2 py-1 transition-colors ${
                workspaceRoot === preset.path
                  ? "border-nexus-accent bg-nexus-accent/15 text-nexus-accent"
                  : "border-nexus-border bg-black/20 hover:bg-nexus-border/40"
              }`}
            >
              {preset.label}
            </button>
          ))}
          {loadingTree ? (
            <span>Carregando árvore...</span>
          ) : (
            <span>{tree.length} raiz(es)</span>
          )}
          <button
            onClick={() => void loadTree()}
            className="rounded-md border border-nexus-border px-3 py-1.5 hover:bg-nexus-border/50"
          >
            <RefreshCw className="mr-1 inline-block h-3 w-3" />
            Recarregar
          </button>
          <button
            type="button"
            onClick={() => setExplorerCollapsed((prev) => !prev)}
            className="rounded-md border border-nexus-border px-3 py-1.5 hover:bg-nexus-border/50"
            title={explorerCollapsed ? "Mostrar explorer" : "Ocultar explorer"}
          >
            {explorerCollapsed ? (
              <ChevronRight className="inline-block h-3 w-3" />
            ) : (
              <ChevronLeft className="inline-block h-3 w-3" />
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div
        className={`grid min-h-0 flex-1 gap-3 ${explorerCollapsed ? "grid-cols-[1fr]" : "grid-cols-[280px_minmax(0,1fr)]"}`}
      >
        {!explorerCollapsed && (
          <section className="overflow-hidden rounded-lg border border-nexus-border bg-nexus-panel/60">
            <div className="border-b border-nexus-border px-4 py-3 text-xs uppercase tracking-wide text-gray-500">
              Explorer
            </div>
            <div className="h-full overflow-auto p-3">
              <FileExplorer
                tree={tree}
                activePath={activePath}
                loading={loadingTree}
                onSelectFile={(path: string) => void loadFile(path)}
              />
            </div>
          </section>
        )}

        <section className="flex min-h-0 flex-col gap-3">
          <div className="overflow-hidden rounded-lg border border-nexus-border bg-nexus-panel/60">
            <div className="flex items-center justify-between border-b border-nexus-border px-4 py-3">
              <div>
                <p className="text-sm font-medium">
                  {activePath || "Nenhum ficheiro selecionado"}
                </p>
                <p className="text-xs text-gray-500">
                  {language} •{" "}
                  {dirty ? "alterações por guardar" : "estado limpo"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => void loadFile(activePath)}
                  className="rounded-md border border-nexus-border px-3 py-1.5 text-xs hover:bg-nexus-border/50"
                >
                  Reabrir
                </button>
                <button
                  onClick={() => void handleSave()}
                  disabled={!dirty || saving || loadingFile || !activePath}
                  className="rounded-md bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-black disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving ? (
                    "A guardar..."
                  ) : (
                    <>
                      <Save className="mr-1 inline-block h-3 w-3" /> Guardar
                    </>
                  )}
                </button>
              </div>
            </div>
            <div className="h-[420px] min-h-[420px]">
              <MonacoEditor
                path={activePath}
                language={language}
                value={content}
                onChange={(next: string) => {
                  setContent(next);
                  setDirty(true);
                }}
              />
            </div>
          </div>

          <div className="flex min-h-[240px] flex-col overflow-hidden rounded-lg border border-nexus-border bg-black/35">
            <div className="flex items-center justify-between border-b border-nexus-border px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <TerminalSquare className="h-4 w-4 text-nexus-accent" />
                Terminal local
              </div>
              <div className="text-xs text-gray-500">
                Execução segura via sandbox
              </div>
            </div>
            <div className="min-h-0 flex-1">
              <Terminal
                command={command}
                onCommandChange={(next: string) => setCommand(next)}
                onRun={() => void handleTerminalRun()}
                running={running}
                results={terminalResults}
              />
            </div>
          </div>
        </section>
      </div>

      <div className="flex items-center gap-2 text-xs text-gray-500">
        <FolderOpen className="h-3.5 w-3.5" />
        <span>
          {desktopMode
            ? "O modo desktop usa o seletor nativo do Mac e dá acesso real à pasta escolhida."
            : "O workspace usa ficheiros locais reais e grava alterações diretamente na pasta selecionada."}
        </span>
        {dirty && (
          <span className="text-amber-300">• alterações pendentes</span>
        )}
      </div>
    </div>
  );
}
