/**
 * Groups equivalent bot-group failures into one incident per turn.
 *
 * The transcript stays chronological: a user message starts a new turn, and
 * error messages that share the same normalised text inside that turn collapse
 * into a single incident. The original messages are kept, in order, so the
 * technical history can still be opened.
 */

export interface GroupTranscriptMessage {
  id: string;
  role: "user" | "assistant" | "error" | "coordinator" | "decision";
  content: string;
  bot_id: string | null;
  bot_name: string | null;
  created_at: string;
  /**
   * Durable execution identity. Present on the new composer path
   * (`run_id` is shared by the run, its messages and every SSE frame).
   * Absent on legacy responses, where the UI must fall back without
   * pretending a terminal state was persisted.
   */
  run_id?: string | null;
  /** Total order of the run's events; only comparable inside one `run_id`. */
  seq?: number | null;
}

export function groupRoleLabel(message: GroupTranscriptMessage): string | undefined {
  if (message.role === "coordinator") return "Coordenador";
  if (message.role === "decision") return "Decisão";
  return undefined;
}

/**
 * The run that owns the turn currently visible to the operator.
 *
 * A user message is the turn boundary: when it carries a `run_id`, that id is
 * authoritative even if an older run is still listed. When the latest user
 * message predates the run envelope, fall back to the first assistant/error
 * message that carries one. Returning `null` is deliberate: the caller must
 * not attach an old run to a new turn.
 */
export function transcriptRunId(messages: GroupTranscriptMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message) continue;
    if (message.role === "user") return message.run_id?.trim() || null;
    if (message.run_id?.trim()) return message.run_id;
  }
  return null;
}

/**
 * Merge a server page into the transcript without duplicating rows.
 *
 * Existing rows keep their position (the live stream already ordered them);
 * the persisted server copy replaces the text in place. Rows that only exist
 * on the server are appended in server order. `loadOlder` uses a separate
 * prepend path because those rows belong before the current page.
 */
export function mergeGroupMessages(
  current: GroupTranscriptMessage[],
  incoming: GroupTranscriptMessage[],
): GroupTranscriptMessage[] {
  const server = new Map(incoming.map((message) => [message.id, message]));
  const merged = current.map((message) => server.get(message.id) ?? message);
  const known = new Set(merged.map((message) => message.id));
  for (const message of incoming) {
    if (known.has(message.id)) continue;
    known.add(message.id);
    merged.push(message);
  }
  return merged;
}

export interface GroupIncident {
  kind: "incident";
  id: string;
  fingerprint: string;
  messages: GroupTranscriptMessage[];
  /** The user message that opened this turn, when one exists. */
  turnUser: GroupTranscriptMessage | null;
}

export type GroupTimelineItem =
  | { kind: "message"; message: GroupTranscriptMessage }
  | GroupIncident;

export function normalizeIncidentText(content: string): string {
  return content.replace(/\s+/g, " ").trim().toLocaleLowerCase("pt");
}

export function groupEquivalentErrors(messages: GroupTranscriptMessage[]): GroupTimelineItem[] {
  const items: GroupTimelineItem[] = [];
  let turnUser: GroupTranscriptMessage | null = null;
  const open = new Map<string, number>();

  const resetTurn = () => {
    open.clear();
  };

  for (const message of messages) {
    if (message.role === "user") {
      turnUser = message;
      resetTurn();
      items.push({ kind: "message", message });
      continue;
    }
    if (message.role !== "error") {
      items.push({ kind: "message", message });
      continue;
    }
    const fingerprint = normalizeIncidentText(message.content);
    const existing = open.get(fingerprint);
    if (existing !== undefined) {
      const item = items[existing];
      if (item?.kind === "incident") item.messages.push(message);
      continue;
    }
    open.set(fingerprint, items.length);
    items.push({
      kind: "incident",
      id: message.id,
      fingerprint,
      messages: [message],
      turnUser,
    });
  }
  return items;
}

export function affectedAgents(incident: GroupIncident): string[] {
  const names: string[] = [];
  for (const message of incident.messages) {
    const name = message.bot_name?.trim() || "Agente sem nome";
    if (!names.includes(name)) names.push(name);
  }
  return names;
}
