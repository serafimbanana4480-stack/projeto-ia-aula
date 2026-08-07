"use client";
import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import { FileText, Upload, Link2, X } from "lucide-react";

function formatBytes(bytes: number): string {
  if (bytes < 1e3) return `${bytes} B`;
  if (bytes < 1e6) return `${(bytes / 1e3).toFixed(1)} KB`;
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

export default function PdfPage() {
  const [pdfUrl, setPdfUrl] = useState<string>("");
  const [fileName, setFileName] = useState<string>("");
  const [fileSize, setFileSize] = useState<number | null>(null);
  const [urlInput, setUrlInput] = useState<string>("");
  const [error, setError] = useState<string>("");
  const objectUrlRef = useRef<string>("");

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
    };
  }, []);

  const clearCurrent = () => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = "";
    }
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError("");
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.type !== "application/pdf") {
      setError("O ficheiro selecionado não é um PDF.");
      return;
    }
    clearCurrent();
    const url = URL.createObjectURL(file);
    objectUrlRef.current = url;
    setPdfUrl(url);
    setFileName(file.name);
    setFileSize(file.size);
  };

  const handleUrlLoad = () => {
    setError("");
    const value = urlInput.trim();
    if (!value) return;
    if (!/^https?:\/\//i.test(value)) {
      setError("Insere um URL válido que comece por http:// ou https://");
      return;
    }
    clearCurrent();
    setPdfUrl(value);
    setFileName(value.split("/").pop() || value);
    setFileSize(null);
  };

  const handleClear = () => {
    clearCurrent();
    setPdfUrl("");
    setFileName("");
    setFileSize(null);
    setUrlInput("");
    setError("");
  };

  return (
    <AppShell title="Leitor PDF">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mx-auto flex h-full max-w-5xl flex-col"
      >
        <div className="mb-6 flex items-center gap-3">
          <FileText className="h-6 w-6 text-nexus-accent" />
          <h1 className="text-2xl font-bold">Leitor PDF</h1>
        </div>

        <div className="card mb-4 p-4">
          <div className="flex flex-col gap-4 md:flex-row md:items-center">
            <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card px-4 py-2 text-sm text-nexus-text transition-colors hover:border-nexus-accent">
              <Upload className="h-4 w-4 text-nexus-accent" />
              Selecionar ficheiro
              <input
                type="file"
                accept="application/pdf"
                onChange={handleFile}
                className="hidden"
              />
            </label>

            <div className="flex flex-1 items-center gap-2">
              <div className="flex flex-1 items-center gap-2 rounded-lg border border-nexus-border bg-nexus-card px-3 py-2">
                <Link2 className="h-4 w-4 text-nexus-muted" />
                <input
                  type="text"
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleUrlLoad()}
                  placeholder="https://exemplo.com/documento.pdf"
                  className="flex-1 bg-transparent text-sm text-nexus-text outline-none placeholder:text-nexus-muted"
                />
              </div>
              <button
                onClick={handleUrlLoad}
                className="rounded-lg border border-nexus-border bg-nexus-card px-4 py-2 text-sm text-nexus-text transition-colors hover:border-nexus-accent"
              >
                Abrir URL
              </button>
            </div>

            {pdfUrl && (
              <button
                onClick={handleClear}
                className="flex items-center gap-1.5 rounded-lg border border-nexus-border px-3 py-2 text-sm text-nexus-muted transition-colors hover:text-red-400"
              >
                <X className="h-4 w-4" />
                Limpar
              </button>
            )}
          </div>

          {error && (
            <div className="mt-3 text-sm text-red-400">{error}</div>
          )}

          {pdfUrl && (
            <div className="mt-3 flex items-center gap-2 text-xs text-nexus-muted">
              <FileText className="h-3.5 w-3.5" />
              <span className="font-medium text-nexus-text">{fileName}</span>
              {fileSize != null && <span>· {formatBytes(fileSize)}</span>}
            </div>
          )}
        </div>

        {pdfUrl ? (
          <div className="card flex-1 overflow-hidden p-0">
            <iframe
              src={pdfUrl}
              title="PDF"
              className="h-[calc(100vh-260px)] w-full"
            />
          </div>
        ) : (
          <div className="card flex flex-1 flex-col items-center justify-center gap-3 py-20 text-center">
            <FileText className="h-12 w-12 text-nexus-muted" />
            <div className="text-lg font-medium text-nexus-text">
              Nenhum PDF carregado
            </div>
            <p className="max-w-md text-sm text-nexus-muted">
              Seleciona um ficheiro PDF ou insere um URL para o visualizar
              diretamente no navegador.
            </p>
          </div>
        )}
      </motion.div>
    </AppShell>
  );
}
