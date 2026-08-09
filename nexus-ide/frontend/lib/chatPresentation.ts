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
    .replace(/<\/?(?:tool_call|tool|event|think|thinking)>/gi, "");

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
  const kind = String(data.kind ?? "status") as ActivityItem["kind"];
  const status = String(data.status ?? "running") as ActivityItem["status"];
  const taskId = String(data.task_id ?? "");
  const detail = sanitizeAssistantContent(event.content ?? "");

  return {
    id: taskId || `activity-${index}-${event.timestamp}`,
    kind,
    title: EVENT_TITLES[eventName] ?? "A avançar com a tarefa",
    detail: detail || undefined,
    agent: event.agent as AgentName | undefined,
    status,
    timestamp: event.timestamp,
    data,
  };
}

export function agentActivity(
  event: StreamEvent,
  index: number,
  status: "running" | "success",
): ActivityItem {
  const delegated = Boolean(event.data?.delegated);
  return {
    id: `agent-${event.agent ?? "AI"}-${String(event.data?.task_id ?? index)}`,
    kind: "agent",
    title:
      status === "running"
        ? delegated
          ? `${event.agent ?? "Agente"} recebeu trabalho delegado`
          : `${event.agent ?? "IA"} começou a trabalhar`
        : `${event.agent ?? "Agente"} concluiu a sua parte`,
    agent: event.agent,
    status,
    timestamp: event.timestamp,
    data: event.data,
  };
}
