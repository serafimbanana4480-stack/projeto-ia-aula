import type { UsageSnapshot } from "../stores/chatTelemetryStore";
import type { StreamEvent } from "./types";

export interface ContextSegment {
  key: string;
  label: string;
  value: number;
  color: string;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

/** Session usage only. Global message totals are never a model context snapshot. */
export function deriveContextUsage(usage: UsageSnapshot | null, modelWindow = 0) {
  const context = usage?.context;
  const reportedWindow = count(context?.context_window);
  const window = reportedWindow !== null && reportedWindow > 0 ? reportedWindow
    : Number.isFinite(modelWindow) && modelWindow > 0 ? modelWindow : null;
  const segments: ContextSegment[] = [];
  const add = (key: string, label: string, value: unknown, color: string) => {
    const tokens = count(value);
    if (tokens !== null) segments.push({ key, label, value: tokens, color });
  };
  if (context) {
    // MCP is included in the legacy tools total. Split it once for the chart.
    const tools = count(context.tools);
    const mcp = Math.min(count(context.mcp) ?? 0, tools ?? count(context.mcp) ?? 0);
    add("prompt", "Pedido", context.prompt ?? context.conversation, "var(--nx-accent-bright)");
    add("history", "Histórico", context.history, "var(--nx-cyan)");
    add("project", "Projeto", context.project, "var(--nx-rose)");
    add("files", "Ficheiros", context.files ?? context.attachments, "#60a5fa");
    add("memory", "Memória", context.memory, "var(--nx-amber)");
    add("tools", "Ferramentas", tools === null ? undefined : Math.max(0, tools - mcp), "#fb923c");
    if (count(context.mcp) !== null) add("mcp", "MCP", mcp, "#a78bfa");
    add("reasoning", "Raciocínio", context.reasoning, "#e879f9");
    add("response", "Resposta", context.response, "var(--nx-emerald)");
    add("system", "Sistema", context.system, "var(--nx-text-faint)");
  }
  const known = segments.reduce((sum, segment) => sum + segment.value, 0);
  // Providers report billed input/output separately. Output must not be added
  // to input a second time to invent the current window occupancy.
  const used = count(context?.total) ?? (segments.length ? known : count(usage?.input_tokens));
  if (!segments.length && used !== null) {
    add("input", "Entrada reportada", used, "var(--nx-accent-bright)");
  } else if (used !== null && used > known) {
    add("other", "Sem detalhe", used - known, "var(--nx-text-faint)");
  }
  const source = !usage ? "unknown" : context
    ? context.source === "provider" ? "provider" : "estimated"
    : usage.source === "provider" ? "provider" : "estimated";
  const percent = used !== null && window !== null && window > 0 ? (used / window) * 100 : null;
  return { segments, used, window, percent, source, total: Math.max(known, used ?? 0, 1) };
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

/** Only successful load_skill results count as loaded instructions. */
export function loadedSkillsFromEvents(events: StreamEvent[]): string[] {
  const skills = new Set<string>();
  for (const event of events) {
    if (event.type !== "tool_result" || event.tool_name !== "load_skill" || event.tool_error) continue;
    const outer = record(event.tool_result);
    if (!outer || outer.ok === false || outer.error || outer.confirmation_required) continue;
    const result = record(outer.result) ?? outer;
    if (result.ok === false || result.error) continue;
    if (typeof result.name === "string" && result.name.trim()) skills.add(result.name);
  }
  return [...skills];
}
