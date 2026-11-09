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
  role: "user" | "assistant" | "error";
  content: string;
  bot_id: string | null;
  bot_name: string | null;
  created_at: string;
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
