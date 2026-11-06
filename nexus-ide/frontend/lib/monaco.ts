/**
 * Local Monaco bootstrap.
 *
 * `@monaco-editor/react` loads Monaco from `cdn.jsdelivr.net` by default. That
 * has two costs in this product:
 *
 *  1. The app's own Content-Security-Policy (`script-src 'self'`) blocks the
 *     CDN, so the editor never initialised — `/editor` threw
 *     "Monaco initialization: error" and rendered an empty pane.
 *  2. An offline-first local IDE should not need the public internet to open
 *     a file.
 *
 * `monaco-editor` is already a dependency, so the editor is served from the
 * app's own origin. The language workers are wired the same way, with a
 * defensive fallback so a bundler that cannot emit a worker still leaves a
 * working (if slightly less clever) editor instead of a blank page.
 */
import { loader, type Monaco } from "@monaco-editor/react";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";

// Language contributions. Without these a file renders as plain text even
// though the syntax highlighter is mounted.
import "monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution";
import "monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution";
import "monaco-editor/esm/vs/basic-languages/python/python.contribution";
import "monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution";
import "monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution";
import "monaco-editor/esm/vs/basic-languages/sql/sql.contribution";
import "monaco-editor/esm/vs/basic-languages/shell/shell.contribution";
import "monaco-editor/esm/vs/basic-languages/html/html.contribution";
import "monaco-editor/esm/vs/basic-languages/css/css.contribution";
import "monaco-editor/esm/vs/language/json/monaco.contribution";
import "monaco-editor/esm/vs/language/css/monaco.contribution";
import "monaco-editor/esm/vs/language/html/monaco.contribution";
import "monaco-editor/esm/vs/language/typescript/monaco.contribution";

type MonacoEnv = {
  getWorker: (moduleId: string, label: string) => Worker;
};

/** A worker that does nothing, used when the bundler cannot emit the real one. */
function inertWorker(): Worker {
  const blob = new Blob(["self.onmessage = function () {};"], {
    type: "text/javascript",
  });
  return new Worker(URL.createObjectURL(blob));
}

function createWorker(path: string): Worker {
  try {
    return new Worker(new URL(path, import.meta.url));
  } catch {
    return inertWorker();
  }
}

let configured = false;

/**
 * Point Monaco at the bundled editor. Idempotent, and safe to call from
 * several components: only the first call installs the loader config.
 */
export function configureLocalMonaco(): typeof monaco {
  if (configured) return monaco;
  configured = true;

  if (typeof self !== "undefined") {
    const env: MonacoEnv = {
      getWorker(_moduleId: string, label: string) {
        switch (label) {
          case "json":
            return createWorker("monaco-editor/esm/vs/language/json/json.worker.js");
          case "css":
          case "scss":
          case "less":
            return createWorker("monaco-editor/esm/vs/language/css/css.worker.js");
          case "html":
          case "handlebars":
          case "razor":
            return createWorker("monaco-editor/esm/vs/language/html/html.worker.js");
          case "typescript":
          case "javascript":
            return createWorker("monaco-editor/esm/vs/language/typescript/ts.worker.js");
          default:
            return createWorker("monaco-editor/esm/vs/editor/editor.worker.js");
        }
      },
    };
    (self as unknown as { MonacoEnvironment: MonacoEnv }).MonacoEnvironment = env;
  }

  // Point the React wrapper at the bundled editor. A failure here must not
  // take the editor down: the wrapper falls back to its own default loader.
  try {
    loader.config({ monaco });
  } catch {
    /* keep the default loader */
  }
  return monaco;
}

export type { Monaco };
