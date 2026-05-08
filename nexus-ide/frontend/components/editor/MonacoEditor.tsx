"use client";
import Editor from "@monaco-editor/react";

// Thin wrapper around Monaco. Configured for VS Code parity.
// See ARCHITECTURE.md §8.4 for AI integrations (inline actions, ghost text,
// diagnostic squiggles, command palette) — to be wired in Phase 5.
export default function MonacoEditor() {
  return (
    <Editor
      height="100%"
      defaultLanguage="typescript"
      defaultValue="// Welcome to NEXUS IDE\n"
      theme="vs-dark"
      options={{
        minimap: { enabled: true },
        fontSize: 13,
        fontFamily: "'SF Mono', Menlo, monospace",
        smoothScrolling: true,
        cursorSmoothCaretAnimation: "on",
      }}
    />
  );
}
