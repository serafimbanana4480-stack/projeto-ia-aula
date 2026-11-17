/**
 * Pure helpers for the bot room. They only describe data the API already
 * returned: no invented progress, health, or collaboration.
 *
 * Group runs carry two identities in the closeout contract:
 *  - `id` is the legacy `bot_group_runs.id`;
 *  - `run_id` is the canonical runtime run id (equal to `id` on PRIMARY).
 * `execution_engine` distinguishes the new `primary` path from `legacy_file`.
 * Every helper below has an explicit fallback for older payloads that carry
 * neither field.
 */

import type { GroupTranscriptMessage } from "../../../lib/groupIncidents";

export interface RoomRunTask {
  id: string;
  bot_id?: string | null;
  bot_name: string;
  provider: string;
  model: string;
  status: string;
  result: string | null;
  error: string | null;
  run_id?: string | null;
  attempt?: number | null;
}

export interface RoomRunRecord {
  id: string;
  task_id: string;
  kind: string;
  payload: Record<string, unknown>;
  seq?: number | null;
}

export interface RoomRun {
  id: string;
  /** Canonical runtime run id; absent on pre-contract rows. */
  run_id?: string | null;
  status: string;
  /** Authoritative `run_state.state`, when the API exposes it. */
  state?: string | null;
  /** Older/nested serialisation of the same authority. */
  run_state?: string | { state?: string | null } | null;
  /** `primary` on the composer path, `legacy_file` on the old executor. */
  execution_engine?: string | null;
  request: string;
  project_root?: string;
  file_path?: string;
  tasks: RoomRunTask[];
  records: RoomRunRecord[];
  created_at?: string | null;
  /** Optional run-level verification payloads from the runtime. */
  verification?: unknown;
  verified?: unknown;
}

const ACTIVE_RUN_STATES = new Set([
  "created",
  "queued",
  "pending",
  "planning",
  "running",
  "verifying",
  "recovering",
  "resuming",
  "cancelling",
  "canceling",
]);

const TERMINAL_RUN_STATES = new Set([
  "completed",
  "failed",
  "cancelled",
  "canceled",
  "expired",
]);

const RESUMABLE_RUN_STATES = new Set([
  "paused",
  "interrupted",
  "failed",
  "pending",
]);

const VERIFICATION_KINDS = new Set([
  "verification",
  "verified",
  "verification_result",
  "definition_of_done",
  "dod",
]);

function isVerificationKind(kind: string): boolean {
  return VERIFICATION_KINDS.has(kind) || /verif|definition_of_done|^dod(?:_|$)/.test(kind);
}

const HANDOFF_KINDS = new Set([
  "handoff",
  "reassignment",
  "reassign",
  "transfer",
  "delegation",
]);

function isHandoffKind(kind: string): boolean {
  return HANDOFF_KINDS.has(kind) || /handoff|reassign|transfer|delegat/.test(kind);
}

/** The durable identity shown and compared by the UI. */
export function runIdentity(run: RoomRun): string {
  return run.run_id?.trim() || run.id;
}

/** Authoritative state when present; the projected status is the fallback. */
export function runState(run: RoomRun): string {
  const nested = typeof run.run_state === "string" ? run.run_state : run.run_state?.state;
  return (run.state?.trim() || nested?.trim() || run.status?.trim() || "").toLocaleLowerCase("en");
}

export function isActiveRunState(state: string | null | undefined): boolean {
  const value = (state ?? "").toLocaleLowerCase("en");
  return ACTIVE_RUN_STATES.has(value) || value.startsWith("waiting_");
}

export function isTerminalRunState(state: string | null | undefined): boolean {
  return TERMINAL_RUN_STATES.has((state ?? "").toLocaleLowerCase("en"));
}

export function runIsHot(runs: RoomRun[]): boolean {
  return runs.some((run) => isActiveRunState(runState(run)));
}

/** Whether this one run is currently live. */
export function runIsActive(run: RoomRun): boolean {
  return isActiveRunState(runState(run));
}

/** Active run first, otherwise the newest run the API returned. */
export function focusRun(runs: RoomRun[]): RoomRun | null {
  return runs.find((run) => isActiveRunState(runState(run))) ?? runs[0] ?? null;
}

/**
 * Run associated with the execution currently visible in the transcript.
 *
 * The caller supplies the id derived from the latest user message (or from a
 * live SSE envelope). A requested id that is not in `runs` yields `null`: an
 * older run must never stand in for a new execution that has not loaded yet.
 * Only when the transcript predates `run_id` do we fall back to an active run
 * and then to the newest run.
 */
export function associatedRun(runs: RoomRun[], runId: string | null | undefined): RoomRun | null {
  const wanted = runId?.trim();
  if (wanted) return runs.find((run) => runIdentity(run) === wanted) ?? null;
  return runs.find((run) => isActiveRunState(runState(run))) ?? runs[0] ?? null;
}

/**
 * Merge a runs page into the local snapshot.
 *
 * Incoming rows win for the same identity, so a run's own state advances.
 * Terminal rows that the server page no longer includes are retained as
 * history; active local rows are not, because a disappeared active run must
 * not look alive forever. A stale HTTP response is rejected upstream by a
 * request ticket, not here.
 */
export function mergeRuns(current: RoomRun[], incoming: RoomRun[]): RoomRun[] {
  const seen = new Set<string>();
  const merged: RoomRun[] = [];
  for (const run of incoming) {
    const id = runIdentity(run);
    if (seen.has(id)) continue;
    seen.add(id);
    merged.push(run);
  }
  for (const run of current) {
    const id = runIdentity(run);
    if (seen.has(id)) continue;
    // Keep every settled row the newer page omitted (terminal, paused,
    // blocked, interrupted). Only a vanished *active* row is dropped.
    if (isActiveRunState(runState(run))) continue;
    seen.add(id);
    merged.push(run);
  }
  return merged;
}

export function runStateLabel(state: string | null | undefined): string {
  const value = (state ?? "").trim().toLocaleLowerCase("en");
  if (!value) return "Estado desconhecido";
  if (value.startsWith("waiting_")) return "A aguardar";
  const labels: Record<string, string> = {
    created: "A preparar",
    queued: "Em fila",
    pending: "Pendente",
    planning: "A planear",
    running: "Em execução",
    verifying: "A verificar",
    recovering: "A retomar",
    resuming: "A retomar",
    paused: "Em pausa",
    blocked: "Bloqueada",
    cancelling: "A cancelar",
    canceling: "A cancelar",
    completed: "Concluída",
    completed_with_warnings: "Concluída com avisos",
    failed: "Falhou",
    cancelled: "Cancelada",
    canceled: "Cancelada",
    interrupted: "Interrompida",
    expired: "Expirada",
    skipped: "Não correu",
    partial: "Parcial",
    unresolved: "Sem consenso",
    rejected: "Rejeitada",
  };
  // Unknown non-empty states are surfaced verbatim; the UI never invents a
  // friendlier label for a state it does not understand.
  return labels[value] ?? value;
}

export function executionPhase(input: {
  run?: RoomRun | null;
  streamState?: string | null;
  streamRunId?: string | null;
  streaming?: boolean;
  historyLoading?: boolean;
  runsUnavailable?: boolean;
  hasConversation?: boolean;
}): string {
  if (input.run) return runStateLabel(runState(input.run));
  const streamState = input.streamState?.trim();
  // `done`/`run_status` is an explicit server statement for this session;
  // it is not inferred from the last bot message.
  if (streamState) return runStateLabel(streamState);
  if (input.streaming) return input.streamRunId ? "Em execução" : "A iniciar";
  if (input.historyLoading) return "A carregar estado…";
  if (input.runsUnavailable) return "Estado indisponível";
  if (input.hasConversation) return "Sem execução registada";
  return "Em espera";
}

export function canResumeRun(run: RoomRun): boolean {
  return RESUMABLE_RUN_STATES.has(runState(run));
}

export function canCancelRun(run: RoomRun): boolean {
  return isActiveRunState(runState(run));
}

export function runEngineLabel(run: RoomRun): string {
  const engine = run.execution_engine?.trim().toLocaleLowerCase("en");
  if (engine === "primary") return "PRIMARY";
  if (engine === "legacy_file") return "Leitura de ficheiro";
  // Old payloads do not carry an engine; say so instead of inventing one.
  return "Motor não indicado";
}

export function recordKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    tool_call: "Chamada de ferramenta",
    tool_result: "Resultado da ferramenta",
    handoff: "Passagem ao participante seguinte",
    reassignment: "Reatribuição",
    reassign: "Reatribuição",
    transfer: "Transferência",
    delegation: "Delegação",
    verification: "Verificação",
    verified: "Resultado verificado",
    verification_result: "Resultado da verificação",
    definition_of_done: "Definição de concluído",
    dod: "Definição de concluído",
  };
  return labels[kind] ?? kind;
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function payloadRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function verificationVerdict(payload: Record<string, unknown>): boolean | null {
  if (typeof payload.verified === "boolean") return payload.verified;
  const raw = firstString(payload.verdict, payload.result, payload.status, payload.outcome).toLocaleUpperCase("en");
  if (["PASS", "PASSED", "VERIFIED", "OK", "SUCCESS", "SATISFIED"].includes(raw)) return true;
  if (["FAIL", "FAILED", "REJECTED", "UNVERIFIED", "BLOCKED", "UNSATISFIED"].includes(raw)) return false;
  return null;
}

function verificationDetail(payload: Record<string, unknown>): string {
  return firstString(
    payload.detail,
    payload.summary,
    payload.reason,
    payload.message,
    payload.content,
    payload.verdict,
    typeof payload.verified === "boolean" ? (payload.verified ? "Resultado verificado" : "Resultado não aprovado") : "",
  );
}

export interface RoomVerification {
  id: string;
  taskId: string | null;
  kind: string;
  label: string;
  detail: string;
  /** `true` verified, `false` rejected, `null` recorded without explicit verdict. */
  verified: boolean | null;
}

export interface RoomHandoff {
  id: string;
  kind: string;
  from: string;
  to: string;
  detail: string;
}

function verificationFromPayload(
  id: string,
  taskId: string | null,
  kind: string,
  payload: Record<string, unknown>,
): RoomVerification {
  return {
    id,
    taskId,
    kind,
    label: firstString(payload.label, payload.name, payload.check, payload.summary) || recordKindLabel(kind),
    detail: verificationDetail(payload),
    verified: verificationVerdict(payload),
  };
}

/**
 * Verification evidence explicitly recorded by the runtime.
 *
 * A completed bot message is deliberately NOT verification. When no record
 * exists the UI must say so instead of presenting the last answer as proof.
 */
export function verificationOf(run: RoomRun): RoomVerification[] {
  const entries: RoomVerification[] = [];
  for (const record of run.records) {
    if (!isVerificationKind(record.kind)) continue;
    entries.push(verificationFromPayload(record.id, record.task_id || null, record.kind, record.payload));
  }
  const explicit = run.verification;
  const addExplicit = (value: unknown, index: number) => {
    if (typeof value === "boolean") {
      entries.push({
        id: `${runIdentity(run)}:verification:${index}`,
        taskId: null,
        kind: "verification",
        label: recordKindLabel("verification"),
        detail: value ? "Resultado verificado" : "Resultado não aprovado",
        verified: value,
      });
      return;
    }
    const payload = payloadRecord(value);
    if (payload) {
      entries.push(verificationFromPayload(
        firstString(payload.id) || `${runIdentity(run)}:verification:${index}`,
        firstString(payload.task_id) || null,
        firstString(payload.kind) || "verification",
        payload,
      ));
      return;
    }
    const text = firstString(value);
    if (text) {
      entries.push({
        id: `${runIdentity(run)}:verification:${index}`,
        taskId: null,
        kind: "verification",
        label: recordKindLabel("verification"),
        detail: text,
        verified: null,
      });
    }
  };
  if (Array.isArray(explicit)) explicit.forEach(addExplicit);
  else if (explicit !== undefined && explicit !== null) addExplicit(explicit, 0);
  if (typeof run.verified === "boolean") {
    entries.push({
      id: `${runIdentity(run)}:verified`,
      taskId: null,
      kind: "verified",
      label: recordKindLabel("verified"),
      detail: run.verified ? "Resultado verificado" : "Resultado não aprovado",
      verified: run.verified,
    });
  }
  return entries;
}

export function taskVerification(run: RoomRun, taskId: string): RoomVerification | null {
  return verificationOf(run).find((entry) => entry.taskId === taskId && entry.verified === true) ?? null;
}

function taskName(run: RoomRun, id: string): string {
  return run.tasks.find((task) => task.id === id)?.bot_name ?? "";
}

/** Explicit handoffs/reassignments, with legacy `source_*` payload support. */
export function handoffRecords(run: RoomRun): RoomHandoff[] {
  const handoffs: RoomHandoff[] = [];
  for (const record of run.records) {
    if (!isHandoffKind(record.kind)) continue;
    const payload = record.payload;
    const task = run.tasks.find((item) => item.id === record.task_id);
    const sourceTask = firstString(payload.source_task_id);
    const from = firstString(
      payload.from,
      payload.from_bot,
      payload.from_bot_name,
      payload.from_agent,
      payload.source,
      payload.previous,
      sourceTask ? taskName(run, sourceTask) : "",
      taskName(run, firstString(payload.source_bot_id)),
    );
    const to = firstString(
      payload.to,
      payload.to_bot,
      payload.to_bot_name,
      payload.to_agent,
      payload.target,
      payload.next,
      task?.bot_name,
    );
    handoffs.push({
      id: record.id,
      kind: record.kind,
      from,
      to,
      detail: firstString(payload.reason, payload.detail, payload.message, payload.summary),
    });
  }
  return handoffs;
}

/**
 * Ordering guard for the group SSE relay. Frames without `(run_id, seq)` are
 * legacy frames and stay in arrival order. A replayed `(run_id, seq)` or an
 * event older than the last accepted one for that run is dropped.
 */
export class GroupStreamOrder {
  private readonly seen = new Set<string>();
  private readonly lastSeq = new Map<string, number>();

  accept(event: { run_id?: string; seq?: number }): boolean {
    const runId = typeof event.run_id === "string" ? event.run_id.trim() : "";
    if (!runId || typeof event.seq !== "number" || !Number.isFinite(event.seq)) return true;
    const key = `${runId}:${event.seq}`;
    if (this.seen.has(key)) return false;
    const last = this.lastSeq.get(runId);
    if (last !== undefined && event.seq <= last) return false;
    this.seen.add(key);
    this.lastSeq.set(runId, event.seq);
    return true;
  }
}

/** Attach the frame envelope to a message when the payload omitted it. */
export function withStreamEnvelope<T extends GroupTranscriptMessage>(
  message: T,
  event: { run_id?: string; seq?: number },
): T {
  const runId = message.run_id?.trim() || event.run_id?.trim() || null;
  const seq = typeof message.seq === "number" ? message.seq : (event.seq ?? null);
  if (message.run_id === runId && message.seq === seq) return message;
  return { ...message, run_id: runId, seq };
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
    case "blocked": return "Bloqueado";
    case "paused": return "Em pausa";
    case "resuming": return "A retomar";
    case "verifying": return "A verificar";
    default: return input.configured ? "Em espera" : "Por configurar";
  }
}

/**
 * Role of a bot inside a legacy file-reading run. Mirrors the order the backend
 * assigns: the first participant reads, the last reviews, the middle ones
 * contribute. Not used for PRIMARY tasks, where the plan owns the assignment.
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
    blocked: "Bloqueada",
    paused: "Em pausa",
    resuming: "A retomar",
    verifying: "A verificar",
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
