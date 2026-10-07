import type { Tool } from "./types";

export const TOOL_GROUPS = [
  { id: "planning", label: "Planeamento" },
  { id: "code", label: "Código e ficheiros" },
  { id: "research", label: "Pesquisa" },
  { id: "skills", label: "Skills" },
  { id: "context", label: "Memória e contexto" },
  { id: "agents", label: "Agentes" },
  { id: "integrations", label: "Integrações" },
  { id: "system", label: "Sistema" },
] as const;

export type ToolGroup = (typeof TOOL_GROUPS)[number]["id"];

export function toolGroup(tool: Pick<Tool, "name" | "category">): ToolGroup {
  const name = tool.name;
  if (/skill/.test(name)) return "skills";
  if (/^(todo_|sequential_thinking|schedule_task|list_tasks|cancel_task)/.test(name)) return "planning";
  if (/context|memory|knowledge|user_profile|user_preferences|remember_fact|index_/.test(name)) return "context";
  if (/agent|spawn_task|bus_|session|cancel_run/.test(name)) return "agents";
  if (/^(mcp_|docker_|db_|api_request|send_|.*email|.*inbox|git_push)/.test(name)) return "integrations";
  if (/search_web|web_search|fetch_|search_docs|deep_research|search_and_answer|search_github|browser_/.test(name)) return "research";
  if (/file|dir|project|code|tests|lint|type_check|shell|script|git_|dependencies|dependency|symbols/.test(name)) return "code";
  return "system";
}

export function toolAvailability(tool: Tool): { id: string; label: string; tone: "success" | "warning" | "danger" | "neutral" } {
  if (tool.status === "missing_dependency" || tool.missing_dependency) {
    return { id: "unavailable", label: "Dependência em falta", tone: "danger" };
  }
  if (tool.available === false || tool.status === "unavailable") {
    return { id: "unavailable", label: "Indisponível", tone: "danger" };
  }
  if (!tool.enabled || tool.status === "blocked") {
    return { id: "disabled", label: "Desativada", tone: "neutral" };
  }
  if (tool.requires_confirmation || tool.status === "requires_confirmation") {
    return { id: "confirmation", label: "Pede confirmação", tone: "warning" };
  }
  return { id: "available", label: "Disponível", tone: "success" };
}

export function toolParameters(schema: Record<string, unknown>) {
  const properties = schema.properties;
  const required = Array.isArray(schema.required) ? schema.required : [];
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return [];
  return Object.entries(properties).map(([name, value]) => {
    const field = value && typeof value === "object" ? value as Record<string, unknown> : {};
    return { name, required: required.includes(name), type: typeof field.type === "string" ? field.type : "valor", description: typeof field.description === "string" ? field.description : "" };
  });
}
