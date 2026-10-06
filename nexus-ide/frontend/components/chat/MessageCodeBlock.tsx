"use client";

import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

export default function MessageCodeBlock({
  language,
  code,
  theme,
  maxLines,
}: {
  language: string;
  code: string;
  theme: "dark" | "light" | "system";
  /** When set and the code exceeds it, the block is capped to ~N lines. */
  maxLines?: number;
}) {
  const lineCount = code.split("\n").length;
  const capped = typeof maxLines === "number" && maxLines > 0 && lineCount > maxLines;
  const body = (
    <SyntaxHighlighter
      language={language}
      style={theme === "light" ? oneLight : oneDark}
      customStyle={{
        margin: 0,
        borderRadius: "0.75rem",
        fontSize: "0.78rem",
        lineHeight: "1.65",
        padding: "2.5rem 1rem 1rem",
        background: "var(--nx-bg)",
      }}
      PreTag="div"
      showLineNumbers={lineCount > 3}
    >
      {code}
    </SyntaxHighlighter>
  );
  if (!capped) return body;
  return (
    <div
      className="relative overflow-hidden rounded-lg"
      style={{ maxHeight: `${(maxLines as number) * 21}px` }}
    >
      {body}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-nexus-bg to-transparent"
      />
    </div>
  );
}
