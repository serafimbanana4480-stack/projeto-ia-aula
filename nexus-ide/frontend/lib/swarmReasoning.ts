/**
 * Reasoning extraction for the SWARM lane.
 *
 * `POST /api/swarm/run` is a **synchronous** endpoint: it returns the whole
 * `SwarmResult` in one response and there is no server-sent event stream. The
 * result carries no `reasoning` field either — `backend/swarm/core/types.py`
 * defines `final_answer`, `decisions`, `proposals`, `reviews`, `messages`,
 * `scores`, `evidence_used` and nothing else. So the swarm reasoning block
 * cannot be fed incrementally from the wire; what it *can* be fed is the run's
 * real reasoning artifacts, which this module assembles in a stable order.
 *
 * Everything here is derived from fields the run actually produced. Nothing is
 * synthesised: if a run emitted no decisions, proposals or reviews, the
 * function returns whatever the answer itself had to say about its approach,
 * and if that is empty too, an empty string — which `ThinkingBlock` renders as
 * nothing at all. That is the honest outcome, and better than a placeholder.
 */
import { sanitizeAssistantContent } from "./chatPresentation";

interface WireFrame {
  [key: string]: unknown;
}

function isFrame(value: unknown): value is WireFrame {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function frames(value: unknown): WireFrame[] {
  return Array.isArray(value) ? value.filter(isFrame) : [];
}

function text(value: unknown): string {
  if (typeof value !== "string") return "";
  // `<thinking>`/`<reasoning>` markup is transport, not content. The NEW
  // swarm lane never stripped it: `backend/swarm/core/orchestrator.py:589`
  // passes `enable_thinking=False` to the agent, but only the LEGACY lane
  // (`backend/orchestrator/swarm.py:958`) calls `_strip_thinking_markup`. A
  // model that ignores the flag therefore leaks literal tags into the swarm
  // answer, so the frontend removes them here — the same rule the chat lane
  // applies in `sanitizeAssistantContent`.
  return sanitizeAssistantContent(value).trim();
}

function line(label: string, body: string): string | null {
  const clean = text(body);
  if (!clean) return null;
  return label ? `**${label}** — ${clean}` : clean;
}

function label(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

/**
 * Assembles the run's reasoning into markdown-ish plain text.
 *
 * Order is Coordinator decisions → proposals → reviewer summaries, because
 * that is the order the swarm produced them in. Each entry is prefixed with its
 * own title so the block reads as a trace rather than a wall of prose.
 */
export function swarmReasoningText(result: unknown): string {
  if (!isFrame(result)) return "";

  const parts: string[] = [];

  for (const decision of frames(result.decisions)) {
    const heading = label(decision.title, "Decisão");
    const body = line(heading, String(decision.rationale ?? ""));
    if (body) parts.push(body);
  }

  for (const proposal of frames(result.proposals)) {
    const heading = label(proposal.title, "Proposta");
    const rationale = text(String(proposal.rationale ?? ""));
    const description = text(String(proposal.description ?? ""));
    // Prefer the author's own rationale; fall back to the description so a
    // proposal that only carries a description is not silently dropped.
    const body = rationale || description;
    const rendered = line(heading, body);
    if (rendered) parts.push(rendered);
  }

  for (const review of frames(result.reviews)) {
    const verdict = review.passed === true ? "aprovada" : "rejeitada";
    const rendered = line(`Revisão ${verdict}`, String(review.summary ?? ""));
    if (rendered) parts.push(rendered);
  }

  if (parts.length === 0) {
    // No structured reasoning in this run. The answer is the only thing the
    // swarm said about how it got there, so quote it rather than invent a
    // trace.
    const answer = text(String(result.final_answer ?? ""));
    if (answer) parts.push(answer);
  }

  return parts.join("\n\n");
}

/**
 * The swarm answer as the chat surface should show it: transport markup
 * removed, never raw.
 */
export function sanitizeSwarmAnswer(result: unknown): string {
  if (!isFrame(result)) return "";
  return text(String(result.final_answer ?? ""));
}
