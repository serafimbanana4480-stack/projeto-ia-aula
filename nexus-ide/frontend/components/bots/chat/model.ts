/**
 * Pure helpers for the bot room. They only describe data the API already
 * returned: no invented progress, health, or collaboration.
 */

export interface RoomRunTask {
  id: string;
  bot_id?: string;
  bot_name: string;
  provider: string;
  model: string;
  status: string;
  result: string | null;
  error: string | null;
}

export interface RoomRunRecord {
  id: string;
  task_id: string;
  kind: string;
  payload: Record<string, unknown>;
}

export interface RoomRun {
  id: string;
  status: string;
  request: string;
  project_root: string;
  file_path: string;
  tasks: RoomRunTask[];
  records: RoomRunRecord[];
}

const ACTIVE_RUN = new Set(["running", "pending", "cancelling"]);

export function focusRun(runs: RoomRun[]): RoomRun | null {
  return runs.find((run) => ACTIVE_RUN.has(run.status)) ?? runs[0] ?? null;
}

export function runIsHot(runs: RoomRun[]): boolean {
  return runs.some((run) => ACTIVE_RUN.has(run.status));
}

export function dayLabel(value: string, now = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const start = (item: Date) => new Date(item.getFullYear(), item.getMonth(), item.getDate()).getTime();
  const diff = Math.round((start(now) - start(date)) / 86_400_000);
  if (diff === 0) return "Hoje";
  if (diff === 1) return "Ontem";
  return date.toLocaleDateString("pt-PT", { day: "numeric", month: "long" });
}

export function mentionRange(value: string, caret: number): { start: number; query: string } | null {
  const upto = value.slice(0, Math.max(0, caret));
  const match = /(?:^|\s)@([^\s@]*)$/.exec(upto);
  if (!match) return null;
  const query = match[1] ?? "";
  return { start: upto.length - query.length - 1, query };
}

export function applyMention(value: string, caret: number, name: string): { value: string; caret: number } | null {
  const range = mentionRange(value, caret);
  if (!range) return null;
  const next = `${value.slice(0, range.start)}@${name} ${value.slice(caret)}`;
  const nextCaret = range.start + name.length + 2;
  return { value: next, caret: nextCaret };
}

export function quoteDraft(author: string, content: string, current: string): string {
  const lines = content.trim().split("\n").slice(0, 6).map((line) => `> ${line}`);
  const block = `${author}:\n${lines.join("\n")}\n\n`;
  return current.trim() ? `${block}${current}` : block;
}

/** What a participant is doing, derived from the live token stream or a run task. */
export function agentActivity(input: {
  name: string;
  configured: boolean;
  partialName: string | null;
  taskStatus?: string | null;
}): string {
  if (input.partialName && input.partialName === input.name) return "A responder";
  switch (input.taskStatus) {
    case "running": return "A executar";
    case "pending": return "À espera";
    case "completed": return "Concluiu";
    case "failed": return "Falhou";
    case "skipped": return "Não correu";
    case "interrupted": return "Interrompida";
    case "cancelled": return "Cancelada";
    case "cancelling": return "A cancelar";
    default: return input.configured ? "Em espera" : "Por configurar";
  }
}

/**
 * Role of a bot inside a file-reading run. Mirrors the order the backend
 * assigns: the first participant reads, the last reviews, the middle ones contribute.
 */
export function fileRunRole(index: number, total: number): string {
  if (total <= 1 || index <= 0) return "Lê o ficheiro";
  if (index === total - 1) return "Revisão crítica";
  return "Contribuição";
}

export function taskStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "Pendente",
    running: "Em curso",
    completed: "Concluída",
    failed: "Falhou",
    interrupted: "Interrompida",
    cancelled: "Cancelada",
    cancelling: "A cancelar",
    skipped: "Não correu",
  };
  return labels[status] ?? status;
}

export function pathsFromRuns(runs: RoomRun[]): string[] {
  const paths: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim() && !paths.includes(value.trim())) paths.push(value.trim());
  };
  for (const run of runs) {
    add(run.file_path);
    for (const record of run.records) add(record.payload.path);
  }
  return paths;
}

export function recordsOfKind(runs: RoomRun[], kinds: string[]): RoomRunRecord[] {
  return runs.flatMap((run) => run.records.filter((record) => kinds.includes(record.kind)));
}

export interface SpeakerRef {
  id: string;
  name: string;
}

export function previousAgentSpeaker(
  items: Array<{ kind: string; message?: { role: string; id: string; bot_id: string | null; bot_name: string | null } }>,
  index: number,
): SpeakerRef | null {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const item = items[cursor];
    if (!item || item.kind !== "message" || !item.message) return null;
    if (item.message.role === "user") return null;
    if (item.message.role === "assistant") {
      return {
        id: item.message.bot_id || item.message.bot_name || item.message.id,
        name: item.message.bot_name || "Agente",
      };
    }
  }
  return null;
}
