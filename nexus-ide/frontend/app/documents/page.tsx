"use client";
import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import {
  FileText,
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  AlertCircle,
  ArrowLeft,
  File,
  Copy,
  Check,
} from "lucide-react";
import { listFiles, readFile, getProjects } from "../../lib/api";
import { useProjectStore } from "../../stores/projectStore";
import type { FileTreeEntry } from "../../lib/types";

export default function DocumentsPage() {
  const { currentProject, setCurrentProject, setProjects } =
    useProjectStore();
  const [tree, setTree] = useState<FileTreeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(["."]));

  const projectPath = currentProject?.path || ".";

  const loadTree = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const entries = await listFiles(projectPath, true, ".");
      setTree(entries);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Não foi possível carregar ficheiros",
      );
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  const loadProjects = useCallback(async () => {
    try {
      const projs = await getProjects();
      setProjects(projs);
      if (!currentProject && projs.length > 0) {
        setCurrentProject(projs[0]);
      }
    } catch {
      // Ignore - projects may not be available
    }
  }, [currentProject, setCurrentProject, setProjects]);

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  const handleFileClick = async (filePath: string) => {
    setSelectedFile(filePath);
    setFileLoading(true);
    setFileContent(null);
    try {
      const result = await readFile(filePath, projectPath);
      setFileContent(result.content);
    } catch {
      setFileContent("Erro ao carregar ficheiro");
    } finally {
      setFileLoading(false);
    }
  };

  const toggleDir = (dirPath: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(dirPath)) {
        next.delete(dirPath);
      } else {
        next.add(dirPath);
      }
      return next;
    });
  };

  const handleCopy = () => {
    if (fileContent) {
      navigator.clipboard.writeText(fileContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const getFileName = (path: string) => path.split("/").pop() || path;

  const renderTree = (entries: FileTreeEntry[], depth: number = 0) => {
    // Sort: directories first, then files, both alphabetically
    const sorted = [...entries].sort((a, b) => {
      if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

    return sorted.map((entry) => {
      const isDir = entry.type === "directory";
      const isExpanded = expandedDirs.has(entry.path);
      const isSelected = selectedFile === entry.path;

      return (
        <div key={entry.path}>
          <button
            onClick={() =>
              isDir ? toggleDir(entry.path) : handleFileClick(entry.path)
            }
            className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-nexus-border/50 ${
              isSelected ? "bg-nexus-accent/15 text-nexus-accent" : "text-gray-300"
            }`}
            style={{ paddingLeft: `${depth * 16 + 8}px` }}
          >
            {isDir ? (
              <>
                {isExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-500" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-500" />
                )}
                {isExpanded ? (
                  <FolderOpen className="h-4 w-4 shrink-0 text-yellow-400" />
                ) : (
                  <Folder className="h-4 w-4 shrink-0 text-yellow-400" />
                )}
              </>
            ) : (
              <>
                <span className="w-3.5" />
                <File className="h-4 w-4 shrink-0 text-gray-500" />
              </>
            )}
            <span className="truncate">{entry.name}</span>
            {!isDir && entry.size > 0 && (
              <span className="ml-auto shrink-0 text-xs text-gray-600">
                {formatSize(entry.size)}
              </span>
            )}
          </button>
          {isDir && isExpanded && entry.children && (
            <div>{renderTree(entry.children, depth + 1)}</div>
          )}
        </div>
      );
    });
  };



  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        <main className="flex-1 overflow-hidden">
          <div className="flex h-full flex-col">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-nexus-border px-6 py-3">
              <div className="flex items-center gap-3">
                <FileText className="h-5 w-5 text-nexus-accent" />
                <h1 className="text-lg font-bold">Documentos</h1>
                {currentProject && (
                  <span className="rounded bg-nexus-border px-2 py-0.5 text-xs text-gray-400">
                    {currentProject.name}
                  </span>
                )}
              </div>
              <button
                onClick={loadTree}
                className="rounded border border-nexus-border px-3 py-1 text-xs text-gray-400 hover:text-gray-200"
              >
                Atualizar
              </button>
            </div>

            <div className="flex flex-1 overflow-hidden">
              {/* File tree sidebar */}
              <div className="w-72 shrink-0 overflow-y-auto border-r border-nexus-border thin-scrollbar">
                {loading && (
                  <div className="flex items-center gap-2 p-4 text-sm text-gray-500">
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
                    A carregar...
                  </div>
                )}

                {error && (
                  <div className="p-4">
                    <div className="flex items-center gap-2 text-sm text-red-400">
                      <AlertCircle className="h-4 w-4" />
                      {error}
                    </div>
                  </div>
                )}

                {!loading && !error && tree.length === 0 && (
                  <div className="p-4 text-center text-sm text-gray-500">
                    Nenhum ficheiro encontrado
                  </div>
                )}

                {!loading && tree.length > 0 && (
                  <div className="py-2">{renderTree(tree)}</div>
                )}
              </div>

              {/* File content viewer */}
              <div className="flex-1 overflow-auto">
                {!selectedFile && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex h-full items-center justify-center text-gray-500"
                  >
                    <div className="text-center">
                      <FileText className="mx-auto mb-3 h-12 w-12 text-gray-700" />
                      <p>Selecione um ficheiro para visualizar</p>
                    </div>
                  </motion.div>
                )}

                {selectedFile && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex h-full flex-col"
                  >
                    {/* File header */}
                    <div className="flex items-center justify-between border-b border-nexus-border px-4 py-2">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setSelectedFile(null)}
                          className="rounded p-1 text-gray-400 hover:text-gray-200"
                        >
                          <ArrowLeft className="h-4 w-4" />
                        </button>
                        <span className="text-sm font-medium">
                          {getFileName(selectedFile)}
                        </span>
                        <span className="text-xs text-gray-500">
                          {selectedFile}
                        </span>
                      </div>
                      <button
                        onClick={handleCopy}
                        className="flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-400 hover:text-gray-200"
                      >
                        {copied ? (
                          <>
                            <Check className="h-3.5 w-3.5 text-green-400" />
                            Copiado
                          </>
                        ) : (
                          <>
                            <Copy className="h-3.5 w-3.5" />
                            Copiar
                          </>
                        )}
                      </button>
                    </div>

                    {/* File content */}
                    <div className="flex-1 overflow-auto">
                      {fileLoading && (
                        <div className="flex items-center gap-2 p-6 text-sm text-gray-500">
                          <div className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
                          A carregar ficheiro...
                        </div>
                      )}

                      {fileContent !== null && !fileLoading && (
                        <pre className="overflow-x-auto p-4 text-sm leading-relaxed text-gray-300">
                          <code>{fileContent}</code>
                        </pre>
                      )}
                    </div>
                  </motion.div>
                )}
              </div>
            </div>
          </div>
        </main>
      </div>

      <BottomHUD />
    </div>
  );
}
