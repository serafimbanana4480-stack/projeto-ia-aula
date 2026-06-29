"use client";
import Editor from "@monaco-editor/react";

interface MonacoEditorProps {
  path: string;
  language: string;
  value: string;
  onChange: (value: string) => void;
}

// Thin wrapper around Monaco. Configured for VS Code parity.
// See ARCHITECTURE.md §8.4 for AI integrations (inline actions, ghost text,
// diagnostic squiggles, command palette) — to be wired in Phase 5.
export default function MonacoEditor({
  path,
  language,
  value,
  onChange,
}: MonacoEditorProps) {
  return (
    <Editor
      height="100%"
      path={path}
      language={language}
      value={value}
      theme="vs-dark"
      onChange={(next) => onChange(next ?? "")}
      options={{
        minimap: { enabled: true },
        fontSize: 13,
        fontFamily: "'SF Mono', Menlo, monospace",
        smoothScrolling: true,
        cursorSmoothCaretAnimation: "on",
        automaticLayout: true,
      }}
    />
  );
}
