"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronDown, ChevronUp, Copy, FileCode2 } from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { useThemeStore } from "../../stores/themeStore";

const COLLAPSED_LINES = 18;

function safeFilePath(value: string): string | null {
  const candidate = value.trim();
  if (!candidate || candidate.length > 180) return null;
  if (candidate.includes("..") || candidate.startsWith("/") || candidate.includes("\\")) return null;
  if (!/^[\w./@-]+\.[A-Za-z0-9]+$/.test(candidate)) return null;
  return candidate;
}

export default function CodeBlock({
  code,
  language,
}: {
  code: string;
  language: string;
}) {
  const theme = useThemeStore((state) => state.theme);
  const router = useRouter();
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const lines = code.split("\n");
  const collapsible = lines.length > COLLAPSED_LINES;
  const visible = !collapsible || expanded ? code : lines.slice(0, COLLAPSED_LINES).join("\n");
  const filePath = safeFilePath(language);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  function openFile() {
    if (!filePath) return;
    try {
      sessionStorage.setItem("nexus.openFile", filePath);
    } catch {
      // The editor still opens; the path is in the label.
    }
    router.push("/editor");
  }

  return (
    <div className="my-3 max-w-full overflow-hidden rounded-lg border border-white/10 bg-[#0c0c12]">
      <div className="flex items-center justify-between gap-2 border-b border-white/10 px-2 py-1">
        <span className="truncate font-mono text-[10px] uppercase tracking-wide text-nexus-muted">
          {language || "texto"}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          {filePath && (
            <button
              type="button"
              onClick={openFile}
              className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10px] text-nexus-muted hover:bg-white/5 hover:text-nexus-text"
            >
              <FileCode2 className="h-3 w-3" />
              Abrir
            </button>
          )}
          {collapsible && (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10px] text-nexus-muted hover:bg-white/5 hover:text-nexus-text"
              aria-expanded={expanded}
            >
              {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {expanded ? "Recolher" : `Expandir (${lines.length})`}
            </button>
          )}
          <button
            type="button"
            onClick={() => void copy()}
            className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10px] text-nexus-muted hover:bg-white/5 hover:text-nexus-text"
            aria-label="Copiar código"
          >
            {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copiado" : "Copiar"}
          </button>
        </div>
      </div>
      <div className="max-w-full overflow-x-auto">
        <SyntaxHighlighter
          language={filePath ? "text" : language || "text"}
          style={theme === "light" ? oneLight : oneDark}
          customStyle={{
            margin: 0,
            borderRadius: 0,
            fontSize: "0.75rem",
            lineHeight: "1.45",
            padding: "0.75rem",
            background: "transparent",
            minWidth: "100%",
          }}
          PreTag="div"
          showLineNumbers={lines.length > 3}
        >
          {visible}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}
