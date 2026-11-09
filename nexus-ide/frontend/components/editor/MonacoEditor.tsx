"use client";
import { useCallback, useEffect, useState } from "react";
import Editor, { type Monaco } from "@monaco-editor/react";
import { configureLocalMonaco } from "../../lib/monaco";

interface MonacoEditorProps {
  path: string;
  language: string;
  value: string;
  onChange: (value: string) => void;
  /** Which design-system surface the editor sits on. Defaults to the deep
   *  editor surface so the match with the rest of the app is not approximate. */
  variant?: "editor" | "well";
}

// Thin wrapper around Monaco. Configured for VS Code parity.
// See ARCHITECTURE.md §8.4 for AI integrations (inline actions, ghost text,
// diagnostic squiggles, command palette) — to be wired in Phase 5.

/** Resolve a `--nx-*` token from the document, with a safe dark fallback. */
function token(monaco: Monaco, name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}

/**
 * The Monaco theme used to be the built-in `vs-dark`, whose palette shares
 * nothing with the app's `--nx-*` tokens: the editor background, selection,
 * line numbers and every syntax colour drifted from the surrounding UI and
 * never changed with the theme switcher. This registers a theme derived from
 * the live tokens instead.
 */
function defineNexusTheme(monaco: Monaco) {
  const bg = token(monaco, "--nx-void", "#0b0c10");
  const surface = token(monaco, "--nx-surface-1", "#15161d");
  const text = token(monaco, "--nx-text", "#f0f0f5");
  const dim = token(monaco, "--nx-text-dim", "#b0b1c2");
  const faint = token(monaco, "--nx-text-faint", "#9294a8");
  const line = token(monaco, "--nx-line", "rgba(255,255,255,0.07)");
  const accent = token(monaco, "--nx-accent-bright", "#9b8cff");
  const cyan = token(monaco, "--nx-cyan", "#22d3ee");
  const emerald = token(monaco, "--nx-emerald", "#34d399");
  const amber = token(monaco, "--nx-amber", "#fbbf24");
  const rose = token(monaco, "--nx-rose", "#fb7185");

  monaco.editor.defineTheme("nexus-ide", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "", foreground: text.replace("#", ""), background: bg.replace("#", "") },
      { token: "comment", foreground: faint.replace("#", ""), fontStyle: "italic" },
      { token: "keyword", foreground: accent.replace("#", "") },
      { token: "string", foreground: emerald.replace("#", "") },
      { token: "number", foreground: amber.replace("#", "") },
      { token: "type", foreground: cyan.replace("#", "") },
      { token: "type.identifier", foreground: cyan.replace("#", "") },
      { token: "function", foreground: cyan.replace("#", "") },
      { token: "variable", foreground: text.replace("#", "") },
      { token: "constant", foreground: amber.replace("#", "") },
      { token: "delimiter", foreground: dim.replace("#", "") },
      { token: "tag", foreground: rose.replace("#", "") },
      { token: "attribute.name", foreground: amber.replace("#", "") },
      { token: "attribute.value", foreground: emerald.replace("#", "") },
    ],
    colors: {
      "editor.background": bg,
      "editor.foreground": text,
      "editorCursor.foreground": accent,
      "editor.lineHighlightBackground": surface,
      "editor.lineHighlightBorder": "#00000000",
      "editor.selectionBackground": `${accent}44`,
      "editor.inactiveSelectionBackground": `${accent}22`,
      "editorLineNumber.foreground": faint,
      "editorLineNumber.activeForeground": text,
      "editorIndentGuide.background": line,
      "editorIndentGuide.activeBackground": `${accent}55`,
      "editorWidget.background": surface,
      "editorWidget.border": line,
      "editorSuggestWidget.background": surface,
      "editorSuggestWidget.border": line,
      "editorSuggestWidget.selectedBackground": `${accent}33`,
      "editorHoverWidget.background": surface,
      "editorHoverWidget.border": line,
      "scrollbarSlider.background": `${faint}33`,
      "scrollbarSlider.hoverBackground": `${faint}55`,
      "editorError.foreground": rose,
      "editorWarning.foreground": amber,
      "editorGutter.background": bg,
      "minimap.background": `${bg}cc`,
    },
  });
}

export default function MonacoEditor({
  path,
  language,
  value,
  onChange,
  variant = "editor",
}: MonacoEditorProps) {
  // The bundled editor is configured on the client only. Until it is ready the
  // component renders the same loading state it always did, so the pane never
  // flashes an empty editor.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    configureLocalMonaco();
    setReady(true);
  }, []);

  const beforeMount = useCallback(
    (monaco: Monaco) => defineNexusTheme(monaco),
    [],
  );

  // A short 420px pane cannot show the whole file shape, so the minimap only
  // costs width there. In the roomy workspace it earns its keep.
  const compact = variant === "well";

  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-nexus-muted">
        A carregar editor…
      </div>
    );
  }

  return (
    <Editor
      height="100%"
      path={path}
      language={language}
      value={value}
      theme="nexus-ide"
      beforeMount={beforeMount}
      onChange={(next) => onChange(next ?? "")}
      loading={
        <div className="flex h-full items-center justify-center text-xs text-nexus-muted">
          A carregar editor…
        </div>
      }
      options={{
        minimap: { enabled: !compact },
        fontSize: 13,
        // Same mono stack the rest of the product uses for code.
        fontFamily:
          "'SF Mono', 'Cascadia Code', 'JetBrains Mono', Menlo, Consolas, monospace",
        fontLigatures: true,
        lineHeight: 20,
        smoothScrolling: true,
        cursorSmoothCaretAnimation: "on",
        automaticLayout: true,
        // Long agent-generated files must wrap rather than force a horizontal
        // scrollbar inside an already narrow pane.
        wordWrap: "on",
        scrollBeyondLastLine: false,
        renderLineHighlight: "line",
        padding: { top: 10, bottom: 10 },
        scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
        tabSize: 2,
        guides: { indentation: true },
      }}
    />
  );
}
