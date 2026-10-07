import type { ActivityItem, AgentName, StreamEvent } from "./types";

const EVENT_TITLES: Record<string, string> = {
  project_defaulted: "Projeto predefinido selecionado",
  agent_warning: "Validação autónoma em curso",
  orchestrator_started: "A preparar a execução",
  orchestrator_finished: "Execução concluída",
  task_started: "Tarefa iniciada",
  task_completed: "Tarefa concluída",
  task_failed: "Tarefa com erro",
  task_cancelled: "Tarefa cancelada",
  agent_retry: "Nova tentativa",
  agent_failed: "Agente encontrou um erro",
  plan_created: "Plano de execução criado",
  step_completed: "Validação concluída",
};

const RUNTIME_EVENT_TITLES: Record<string, string> = {
  command_completed: "Comando concluído",
  file_changed: "Ficheiros alterados",
  file_read: "Ficheiro lido",
  recovery: "A recuperar a execução",
  test_started: "Validação iniciada",
  user_steering: "Orientação recebida",
  waiting_dependency: "À espera de dependência",
};

/**
 * Remove transport syntax produced by tool-capable models.
 *
 * This is also applied to history so conversations saved before structured
 * events were introduced no longer render walls of <tool_call> markup.
 */
function stripBareToolPayloads(value: string): string {
  let text = value;
  const toolStart =
    /(?:^|\n)\s*(?:tool\s*)?\{(?=[\s\S]{0,240}["']?(?:name|tool|tool_name|function)["']?\s*:\s*["'][\w.-]+["'])(?=[\s\S]{0,480}["']?(?:arguments|args|parameters|params)["']?\s*:)/i;

  for (let pass = 0; pass < 100; pass += 1) {
    const match = toolStart.exec(text);
    if (!match) break;
    const braceStart = text.indexOf("{", match.index);
    if (braceStart < 0) break;

    let depth = 0;
    let inString = false;
    let escaped = false;
    let end = -1;
    for (let index = braceStart; index < text.length; index += 1) {
      const char = text[index];
      if (inString) {
        if (escaped) escaped = false;
        else if (char === "\\") escaped = true;
        else if (char === '"') inString = false;
        continue;
      }
      if (char === '"') inString = true;
      else if (char === "{") depth += 1;
      else if (char === "}") {
        depth -= 1;
        if (depth === 0) {
          end = index + 1;
          break;
        }
      }
    }

    if (end < 0) {
      // Malformed repeated calls have no balanced closing brace. Preserve a
      // terminal system warning, if present, and discard the transport wall.
      const terminalMarkers = ["⚠", "[TAREFA NÃO CONCLUÍDA]", "[TASK NOT COMPLETED]"]
        .map((marker) => text.indexOf(marker, braceStart))
        .filter((index) => index >= 0);
      end = terminalMarkers.length > 0 ? Math.min(...terminalMarkers) : text.length;
    }
    text = `${text.slice(0, match.index)}${text.slice(end)}`;
  }
  return text;
}

export function sanitizeAssistantContent(value: string): string {
  const withoutDelimitedTransport = value
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
    // Legacy missions could persist a complete Mission Brief as a fenced
    // assistant token.  Keep old conversations readable after the backend
    // switches to structured mission events.
    .replace(/```(?:markdown|text)?\s*MISSION BRIEF[\s\S]*?```/gi, "")
    .replace(/```tool\b[\s\S]*?(?:```|$)/gi, "")
    .replace(/<tool_call\b[^>]*>[\s\S]*?(?:<\/tool_call>|$)/gi, "")
    .replace(/<tool\b[^>]*>[\s\S]*?(?:<\/tool>|$)/gi, "")
    .replace(/<\|tool_call_begin\|>[\s\S]*?(?:<\|tool_call_end\|>|$)/gi, "")
    .replace(/<event\b[^>]*>[\s\S]*?(?:<\/event>|$)/gi, "")
    .replace(/<\/?(?:function|parameter)[^>]*>/gi, "")
    // Must stay in step with the backend's `strip_reasoning_markup`
    // (`backend/runtime/reasoning.py`), whose pattern is
    // `</?\s*(?:think|thinking|reasoning|scratchpad)\s*>`. The frontend list
    // used to be missing `reasoning` and `scratchpad` and to reject the
    // whitespace variants, so a model that emitted those tags had them shown
    // to the user verbatim in every lane the frontend is the only filter for
    // (the SWARM panel, the SWARM page's "send to chat" box).
    .replace(/<\/?\s*(?:think|thinking|reasoning|scratchpad)\s*>/gi, "")
    .replace(/<\/?(?:tool_call|tool|event)>/gi, "");

  return stripBareToolPayloads(withoutDelimitedTransport)
    .replace(/^\s*tool\s*$/gim, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function activityFromMissionEvent(
  event: StreamEvent,
  index: number,
): ActivityItem {
  const data = event.data ?? {};
  const type = event.type;
  const phaseCount = Array.isArray(data.phases) ? data.phases.length : 0;
  const files = Number(data.files_analyzed ?? 0);
  const tests = Number(data.tests_total ?? 0);
  const findings = Number(data.findings_count ?? 0);
  let title = "Atualização da missão";
  let kind: ActivityItem["kind"] = "status";
  let status: ActivityItem["status"] = "running";

  if (type === "mission_brief") {
    title = "Análise inicial concluída";
    kind = "plan";
  } else if (type === "mission_plan") {
    title = "Plano de execução preparado";
    kind = "plan";
  } else if (type === "mission_completed") {
    title = "Missão concluída";
    status = "success";
  } else if (type === "mission_verification") {
    title = "Validação em curso";
    kind = "verification";
  } else if (type === "mission_agent") {
    title = "Agente especializado atualizado";
    kind = "agent";
  } else if (type === "progress" && data.event === "heartbeat") {
    title = "Ainda a trabalhar";
  }

  const detailParts: string[] = [];
  if (files > 0) detailParts.push(`${files} ficheiros analisados`);
  if (tests > 0) detailParts.push(`${tests} testes identificados`);
  if (findings > 0) detailParts.push(`${findings} achados registados`);
  if (phaseCount > 0) detailParts.push(`${phaseCount} fases`);
  if (typeof data.progress === "number") {
    detailParts.push(`${Math.round(data.progress * 100)}% concluído`);
  }

  return {
    id: String(data.event_id ?? data.mission_id ?? `mission-${index}-${event.timestamp}`),
    kind,
    title,
    detail: event.content?.trim() || detailParts.join(" · ") || undefined,
    agent: event.agent as AgentName | undefined,
    status,
    timestamp: event.timestamp,
    data,
  };
}

export function summarizeApproachContent(value: string): string {
  const clean = sanitizeAssistantContent(value)
    .replace(/\b(?:iteration|passo)\s*:\s*\d+\b/gi, "")
    .trim();
  const parts = clean
    .split(/\n+|(?<=[.!?…])\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const unique = Array.from(new Set(parts));
  return unique
    .slice(0, 4)
    .map((part) => (part.length > 240 ? `${part.slice(0, 237).trimEnd()}…` : part))
    .join("\n");
}

export function activityFromProgress(event: StreamEvent, index: number): ActivityItem {
  const data = event.data ?? {};
  const eventName = String(data.event ?? "");
  const runtimeKind = String(data.kind ?? data.runtime_type ?? "");
  const rawKind = String(data.kind ?? "status");
  let kind: ActivityItem["kind"] =
    rawKind === "plan" || rawKind === "agent" || rawKind === "task" || rawKind === "status" || rawKind === "verification"
      ? rawKind
      : runtimeKind.startsWith("test_")
        ? "verification"
        : runtimeKind.startsWith("subagent_")
          ? "agent"
          : "status";
  if (runtimeKind === "plan_updated") kind = "plan";
  const inferredStatus: ActivityItem["status"] =
    /(?:^|_)(?:failed|error)$/.test(eventName || runtimeKind)
      ? "error"
      : /(?:^|_)(?:cancelled|canceled)$/.test(eventName || runtimeKind)
        ? "cancelled"
        : /(?:^|_)(?:warning|blocked)$/.test(eventName || runtimeKind)
          ? "warning"
        : runtimeKind === "waiting_dependency"
          ? "paused"
          : /(?:^|_)(?:paused|waiting_approval)$/.test(eventName || runtimeKind)
            ? "paused"
      : /(?:^|_)completed$/.test(eventName || runtimeKind) ||
          ["file_read", "file_changed", "user_steering"].includes(runtimeKind)
        ? "success"
        : /(?:^|_)(?:started|progress|output)$/.test(eventName || runtimeKind)
          ? "running"
          : "pending";
  const rawStatus = String(data.status ?? inferredStatus);
  const status: ActivityItem["status"] =
    rawStatus === "pending" ||
    rawStatus === "running" ||
    rawStatus === "success" ||
    rawStatus === "error" ||
    rawStatus === "warning" ||
    rawStatus === "cancelled" ||
    rawStatus === "paused"
      ? rawStatus
      : "pending";
  const taskId = String(data.task_id ?? "");
  const todos = Array.isArray(data.todos) ? data.todos : [];
  const completedTodos = todos.filter((todo) => {
    if (!todo || typeof todo !== "object") return false;
    const todoStatus = String((todo as { status?: unknown }).status ?? "").toLowerCase();
    return ["done", "complete", "completed", "success"].includes(todoStatus);
  }).length;
  const detail =
    runtimeKind === "plan_updated" && todos.length > 0
      ? `${completedTodos} de ${todos.length} etapas concluídas`
      : sanitizeAssistantContent(event.content ?? "");

  return {
    id: taskId || `activity-${index}-${event.timestamp}`,
    kind,
    title:
      runtimeKind === "plan_updated"
        ? "Plano de execução atualizado"
        : EVENT_TITLES[eventName] ?? RUNTIME_EVENT_TITLES[runtimeKind] ?? "A avançar com a tarefa",
    detail: detail || undefined,
    agent: event.agent as AgentName | undefined,
    status,
    timestamp: event.timestamp,
    data,
  };
}

export interface ActivityDisplayGroup {
  key: string;
  items: ActivityItem[];
  fileCount?: number;
}

/** Group only adjacent successful FILE_READ events with explicit numeric counts. */
export function groupAdjacentFileReads(items: ActivityItem[]): ActivityDisplayGroup[] {
  const groups: ActivityDisplayGroup[] = [];
  for (const item of items) {
    const runtimeKind = String(item.data?.kind ?? item.data?.runtime_type ?? item.data?.event ?? "");
    const count = item.data?.count;
    const isCountedRead = runtimeKind === "file_read" && item.status === "success" &&
      typeof count === "number" && Number.isInteger(count) && count > 0;
    const previous = groups.at(-1);
    const previousRuntimeKind = previous?.items[0]
      ? String(previous.items[0].data?.kind ?? previous.items[0].data?.runtime_type ?? previous.items[0].data?.event ?? "")
      : "";
    if (isCountedRead && previous && previousRuntimeKind === "file_read" && previous.fileCount !== undefined) {
      previous.items.push(item);
      previous.fileCount += count;
    } else {
      groups.push({
        key: item.id,
        items: [item],
        ...(isCountedRead ? { fileCount: count } : {}),
      });
    }
  }
  return groups;
}

/**
 * Editorial helpers for progressive disclosure (Activity → Group → Detail → Source).
 * Pure functions so the timeline components stay thin; no behaviour change to
 * the existing fold/sanitize paths above.
 */

/** Compact editorial duration: 2m14s · 4.1s · 500ms. Empty when unknown. */
export function formatRunDuration(ms?: number): string {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSec = ms / 1000;
  if (totalSec < 60) {
    const rounded = Math.round(totalSec * 10) / 10;
    return Number.isInteger(rounded) ? `${rounded}s` : `${rounded.toFixed(1)}s`;
  }
  const m = Math.floor(totalSec / 60);
  const s = Math.round(totalSec - m * 60);
  return `${m}m${String(s).padStart(2, "0")}s`;
}

/** Relative mm:ss clock for the vertical timeline (00:00, 00:03, …). */
export function formatRunClock(ms?: number): string {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return "--:--";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec - m * 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Operational one-liner for a thinking block (“A analisar arquitetura…”). */
export function operationalSummaryForThinking(content: string): string {
  const text = (content ?? "").toLowerCase();
  if (/execut|test|vitest|pytest|spec|suite|build|compil/.test(text)) return "A executar testes…";
  if (/analis|arquitet|architect|structur|design|explor/.test(text)) return "A analisar arquitetura…";
  if (/pesquis|search|web|doc/.test(text)) return "A pesquisar na web…";
  if (/compar|depend|diff/.test(text)) return "A comparar dependências…";
  if (/valid|verific|ambient|env/.test(text)) return "A validar ambiente…";
  if (/plan|migra|tarefa|task|etapa|roadmap/.test(text)) return "A planear migração…";
  if (/inspect|read|\bler\b|a ler|ficheiro|ficheiros/.test(text)) return "A ler ficheiros…";
  if (/edit|escrever|write|cod|refactor|implement/.test(text)) return "A editar código…";
  return "A trabalhar…";
}

export type ToolKindGroup = "web" | "terminal" | "file" | "test" | "other";

export function toolKindGroup(name: string): ToolKindGroup {
  const n = (name ?? "").toLowerCase();
  if (/web_search|search_web|fetch_url|search_github|browser/.test(n)) return "web";
  if (/execute_terminal|execute_code|terminal|shell|command/.test(n)) return "terminal";
  if (/read_file|write_file|list_dir|scaffold|file/.test(n)) return "file";
  if (/test|verify|check/.test(n)) return "test";
  return "other";
}

/** First human-readable string arg (the query / command / path). */
export function primaryToolArg(args: Record<string, unknown> | undefined): string {
  if (!args || typeof args !== "object") return "";
  for (const key of ["query", "q", "command", "cmd", "code", "path", "url", "pattern", "prompt"]) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  for (const value of Object.values(args)) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

/** Sources (3rd disclosure level) extracted from a web tool result. */
export function extractWebSources(result: unknown): string[] {
  if (!result) return [];
  if (typeof result === "string") {
    const urls = result.match(/https?:\/\/[^\s)"']+/g);
    return urls ? Array.from(new Set(urls)).slice(0, 12) : [];
  }
  if (Array.isArray(result)) {
    return result
      .flatMap((item) => extractWebSources(item))
      .filter(Boolean)
      .slice(0, 12);
  }
  if (typeof result === "object") {
    const record = result as Record<string, unknown>;
    const out: string[] = [];
    for (const key of ["sources", "urls", "links", "results", "items", "citations"]) {
      const value = record[key];
      if (Array.isArray(value)) {
        for (const entry of value) {
          if (typeof entry === "string" && entry.trim()) out.push(entry.trim());
          else if (entry && typeof entry === "object") {
            const r = entry as Record<string, unknown>;
            for (const k of ["url", "link", "href", "title", "source"]) {
              if (typeof r[k] === "string" && (r[k] as string).trim()) {
                out.push((r[k] as string).trim());
                break;
              }
            }
          }
        }
      } else if (typeof value === "string" && value.trim()) {
        out.push(value.trim());
      }
    }
    if (out.length > 0) return Array.from(new Set(out)).slice(0, 12);
    return extractWebSources(JSON.stringify(record).slice(0, 4000));
  }
  return [];
}

export function agentActivity(
  event: StreamEvent,
  index: number,
  status: ActivityItem["status"],
): ActivityItem {
  const delegated = Boolean(event.data?.delegated);
  const delegateName = event.data?.target ?? event.data?.name;
  const activityAgent =
    typeof delegateName === "string" && delegateName.trim()
      ? (delegateName as AgentName)
      : event.agent;
  const agent = activityAgent ?? (status === "running" ? "IA" : "Agente");
  const title =
    status === "running"
      ? delegated
        ? `${agent} recebeu trabalho delegado`
        : `${agent} começou a trabalhar`
      : status === "success"
        ? `${agent} concluiu a sua parte`
        : status === "error"
          ? `${agent} terminou com erro`
          : status === "cancelled"
            ? `${agent} foi cancelado`
            : status === "paused"
              ? `${agent} ficou bloqueado ou em pausa`
              : status === "warning"
                ? `${agent} terminou com aviso`
                : `${agent} está pendente`;
  return {
    id: `agent-${activityAgent ?? "AI"}-${String(event.data?.task_id ?? index)}`,
    kind: "agent",
    title,
    agent: activityAgent,
    status,
    timestamp: event.timestamp,
    data: event.data,
  };
}
