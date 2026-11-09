import type { RunStep, StepStatus } from "./types";

/**
 * One quiet line for a tool or a file, in the shape of the work log:
 * "Leu MessageBubble.tsx L1-400", "Pesquisou o padrão", "Executou pytest".
 * Returns null when the step has no path, query or command to name — the
 * caller keeps the existing sentence instead of inventing one.
 */

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

/** A test-start event can close with an explicit `ran: false` result. */
export function verificationWasSkipped(step: Pick<RunStep, "verb" | "detail">): boolean {
  if (step.verb !== "test") return false;
  const detail = asRecord(step.detail);
  return detail?.ran === false || asRecord(detail?.result)?.ran === false;
}

function recordsOf(step: Pick<RunStep, "detail" | "event">): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [];
  const detail = asRecord(step.detail);
  if (detail) {
    records.push(detail);
    for (const key of ["args", "arguments", "tool_args"]) {
      const nested = asRecord(detail[key]);
      if (nested) records.push(nested);
    }
  }
  const data = asRecord(step.event?.data);
  if (data) records.push(data);
  const toolArgs = asRecord(step.event?.tool_args);
  if (toolArgs) records.push(toolArgs);
  return records;
}

function pickString(records: Record<string, unknown>[], keys: string[]): string {
  for (const record of records) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === "string" && value.trim()) return value.trim();
    }
  }
  return "";
}

function pickLine(records: Record<string, unknown>[], keys: string[]): number | null {
  for (const record of records) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === "number" && Number.isInteger(value) && value >= 1) return value;
    }
  }
  return null;
}

function baseName(path: string): string {
  const parts = path.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

function clip(value: string, max = 72): string {
  const clean = value.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max - 1).trimEnd()}…`;
}

/** A bare tool id (`read_file`), not a path or a search pattern. */
function isToolId(value: string): boolean {
  return /^[A-Za-z][A-Za-z0-9_]*$/.test(value);
}

export function lineSpan(records: Record<string, unknown>[]): string {
  const start = pickLine(records, ["start_line", "line_start", "start"]);
  const end = pickLine(records, ["end_line", "line_end", "end"]);
  const offset = pickLine(records, ["offset"]);
  const limit = pickLine(records, ["limit", "max_lines", "n_lines"]);
  const from = start ?? offset;
  if (from === null) return "";
  if (end !== null && end >= from) return ` L${from}-${end}`;
  if (limit !== null) {
    const last = from + limit - 1;
    return last === from ? ` L${from}` : ` L${from}-${last}`;
  }
  return start !== null ? ` L${start}` : "";
}

export function compactActivityLine(step: Pick<RunStep, "kind" | "target" | "verb" | "status" | "detail" | "event">): string | null {
  if (step.verb === "thinking" || step.verb === "agent" || step.verb === "status" || step.verb === "message") {
    return null;
  }
  if (verificationWasSkipped(step)) return "Verificação não executada";
  // Past-tense action labels must not claim a failed, cancelled or pending
  // tool succeeded. The caller renders the actual status instead.
  if (step.status !== "running" && step.status !== "success") return null;
  const records = recordsOf(step);
  const rawPath = pickString(records, ["path", "file", "file_path", "filepath"]);
  const target = (step.target || "").trim();
  const path = rawPath || (target && !isToolId(target) ? target : "");
  const query = pickString(records, ["query", "pattern", "regex", "q"]) || (step.verb !== "file" && target && !isToolId(target) && !path ? target : "");
  const command = pickString(records, ["command", "cmd"]);
  const tool = (isToolId(target) ? target : pickString(records, ["tool_name", "tool"])).toLowerCase();
  const kind = (step.kind || "").toLowerCase();
  const file = path ? baseName(path) : "";
  const span = lineSpan(records);
  const running = step.status === "running";

  const web = /web_search|search_web|fetch_url|browser|open_url/.test(tool) || kind.startsWith("web");
  const search = /grep|search|glob|ripgrep|find/.test(tool) || kind.startsWith("search");
  const shell = step.verb === "command" || /terminal|shell|execute_code|run_command|powershell/.test(tool) || kind.startsWith("command");
  const read = /^(read_file|read_file_absolute|list_dir|list_dir_absolute|get_file_tree|open_file|view_file)/.test(tool)
    || kind.startsWith("file_read") || kind.startsWith("file_list") || kind.startsWith("file_inspect")
    || (step.verb === "file" && /read|list|inspect/.test(kind));
  const edit = /write|edit|patch|create_file|delete_file|str_replace|replace_in_file/.test(tool)
    || kind.startsWith("file_write") || kind.startsWith("file_edit") || kind.startsWith("file_patch") || kind.startsWith("file_changed");

  if (web) {
    const q = pickString(records, ["query", "q", "url"]);
    if (!q) return null;
    return `${running ? "A pesquisar na web" : "Pesquisou na web"} ${clip(q)}`;
  }
  if (search) {
    const q = query || pickString(records, ["query", "pattern"]);
    if (!q) return null;
    const where = path && path !== q ? ` em ${baseName(path)}` : "";
    return `${running ? "A pesquisar" : "Pesquisou"} ${clip(q)}${where}`;
  }
  if (shell) {
    const cmd = command || (target && !isToolId(target) ? target : "");
    if (!cmd) return null;
    return `${running ? "A executar" : "Executou"} ${clip(cmd)}`;
  }
  if (read && file) return `${running ? "A ler" : "Leu"} ${file}${span}`;
  if (edit && file) return `${running ? "A alterar" : "Alterou"} ${file}`;
  if (step.verb === "test") return running ? "A verificar" : "Verificou";
  return null;
}

export function compactToolLine(
  name: string,
  args: Record<string, unknown> | undefined,
  status: string,
): string | null {
  if (status === "unknown") return `${name.replace(/_/g, " ")} · resultado não confirmado`;
  const allowed: StepStatus[] = ["success", "error", "running", "pending", "warning", "paused", "cancelled", "awaiting_confirmation"];
  const stepStatus = allowed.includes(status as StepStatus) ? (status as StepStatus) : "pending";
  return compactActivityLine({
    kind: "tool",
    target: name,
    verb: "tool",
    status: stepStatus,
    detail: args,
  });
}
