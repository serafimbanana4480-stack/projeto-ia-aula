"use client";

/**
 * Group a run's ordered timeline steps into activity groups.
 *
 * The raw timeline is one row per event; a turn with 11 tool calls renders 23
 * rows and the user loses the plot (audit 2026-09-20). This fold keeps the
 * event rows intact — they are still rendered verbatim inside each expanded
 * group — but collapses consecutive tool-ish steps (tool / file / command /
 * test) into a single collapsible "activity group" the way modern agent UIs
 * do. Narrative steps (agent, thinking, status) stay as quiet rows between
 * groups so the story keeps its shape.
 */

import type { RunStep } from "@/lib/types";

const TOOLISH_VERBS: ReadonlySet<RunStep["verb"]> = new Set([
  "tool",
  "file",
  "command",
  "test",
]);

export interface RunStepGroup {
  kind: "tools" | "note";
  /** Steps in this group, in ``seq`` order. */
  steps: RunStep[];
  startSeq: number;
  /** Tool-ish counts (0 for notes). */
  tools: number;
  files: number;
  commands: number;
  tests: number;
  errors: number;
  running: number;
  /** Sum of the durations the runtime measured for these steps. */
  durationMs?: number;
  /** Highest repeat count flagged inside the group (loop detection). */
  maxRepeat?: number;
}

function isEmptyGroup(group: RunStepGroup): boolean {
  return (
    group.steps.length === 0 &&
    group.tools === 0 &&
    group.files === 0 &&
    group.commands === 0 &&
    group.tests === 0 &&
    group.errors === 0 &&
    group.running === 0 &&
    group.durationMs === undefined
  );
}

/** Split an already seq-ordered step list into tool groups + narrative rows. */
export function groupRunSteps(steps: RunStep[]): RunStepGroup[] {
  const groups: RunStepGroup[] = [];
  let current: RunStepGroup | null = null;

  const flush = () => {
    if (current && !isEmptyGroup(current)) groups.push(current);
    current = null;
  };

  const startToolsGroup = (step: RunStep): RunStepGroup => {
    flush();
    current = {
      kind: "tools",
      steps: [step],
      startSeq: step.seq,
      tools: 0,
      files: 0,
      commands: 0,
      tests: 0,
      errors: 0,
      running: 0,
    };
    return current;
  };

  for (const step of steps) {
    if (!TOOLISH_VERBS.has(step.verb)) {
      flush();
      groups.push({
        kind: "note",
        steps: [step],
        startSeq: step.seq,
        tools: 0,
        files: 0,
        commands: 0,
        tests: 0,
        errors: 0,
        running: 0,
      });
      continue;
    }

    if (!current || current.kind !== "tools") {
      current = startToolsGroup(step);
    } else {
      current.steps.push(step);
    }
    const group = current;

    switch (step.verb) {
      case "tool":
        group.tools += 1;
        break;
      case "file":
        group.files += 1;
        break;
      case "command":
        group.commands += 1;
        break;
      case "test":
        group.tests += 1;
        break;
      default:
        break;
    }
    if (step.status === "error") group.errors += 1;
    if (step.status === "running" || step.status === "awaiting_confirmation") {
      group.running += 1;
    }
    if (typeof step.durationMs === "number" && step.durationMs >= 0) {
      group.durationMs = (group.durationMs ?? 0) + step.durationMs;
    }
    if (typeof step.repeatCount === "number" && step.repeatCount > (group.maxRepeat ?? 0)) {
      group.maxRepeat = step.repeatCount;
    }
  }
  flush();
  return groups;
}

/** A short, human title for a tool group — "A ler ficheiros", not debug text. */
export function groupTitle(group: RunStepGroup, isStreaming: boolean): string {
  const live = isStreaming && group.running > 0;
  if (group.tools > 0 && group.files === 0 && group.commands === 0 && group.tests === 0) {
    return live ? "A usar ferramentas" : "Ferramentas";
  }
  if (group.files > 0 && group.tools === 0 && group.commands === 0 && group.tests === 0) {
    return live ? "A ler ficheiros" : "Leitura de ficheiros";
  }
  if (group.commands > 0 && group.tools === 0 && group.tests === 0) {
    return live ? "A executar comandos" : "Comandos executados";
  }
  if (group.tests > 0 && group.tools === 0 && group.commands === 0) {
    return live ? "A validar" : "Validação";
  }
  return live ? "A trabalhar" : "Atividade";
}

export function formatGroupDuration(ms?: number): string {
  if (typeof ms !== "number" || ms <= 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1).replace(".", ",")}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}
