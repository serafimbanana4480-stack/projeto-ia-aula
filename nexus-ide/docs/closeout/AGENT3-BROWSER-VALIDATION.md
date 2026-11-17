# Agent 3 — browser/runtime closeout notes (2026-11-13)

## Browser validation status: **BLOCKED**

The group UI was **not** exercised against a real backend in this environment.

Probe, run from `nexus-ide`:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/health -TimeoutSec 3 -UseBasicParsing
# BACKEND_UNAVAILABLE: Não é possível estabelecer ligação com o servidor remoto

Invoke-WebRequest -Uri http://127.0.0.1:3000 -TimeoutSec 3 -UseBasicParsing
# FRONTEND_UNAVAILABLE: Não é possível estabelecer ligação com o servidor remoto
```

Cause: neither the API (`127.0.0.1:8000`) nor the Next server (`127.0.0.1:3000`)
was running. No backend was simulated for browser validation. The draft below
must run against the real stack (and a real configured group) before this status
changes. Agent 4 owns the final E2E files; this is the hand-off draft.

## Assumed backend contract

### `GET /api/bot-groups/{group_id}/runs`

```json
{
  "runs": [
    {
      "id": "legacy-row-id-or-run-id",
      "run_id": "run-...",
      "execution_engine": "primary",
      "state": "running",
      "status": "running",
      "request": "objetivo do turno",
      "project_root": "C:/projeto",
      "file_path": "",
      "created_at": "2026-11-13T10:00:00Z",
      "tasks": [
        {
          "id": "task-1",
          "bot_id": "bot-1",
          "bot_name": "FORGE",
          "provider": "lmstudio",
          "model": "model",
          "status": "running",
          "attempt": 1,
          "result": null,
          "error": null
        }
      ],
      "records": [
        { "id": "rec-1", "task_id": "task-1", "kind": "tool_call", "payload": { "tool": "run_tests" } },
        { "id": "rec-2", "task_id": "task-1", "kind": "verification", "payload": { "verified": true, "summary": "testes passaram" } },
        { "id": "rec-3", "task_id": "task-2", "kind": "handoff", "payload": { "from": "FORGE", "to": "DEBUGGER" } }
      ],
      "verification": [
        { "task_id": "task-1", "verdict": "PASS", "detail": "testes passaram" }
      ]
    }
  ]
}
```

- `run.run_id` (or `run.id`) is the canonical identity.
- `run.state` (or nested `run.run_state.state`) is authoritative when exposed;
  otherwise `run.status` is the explicit fallback. The UI never infers state
  from `busy`, the last message or a previous run.
- `execution_engine` is `primary` or `legacy_file`. Missing means "Motor não
  indicado" — the UI does not invent an engine.
- Verification is only what `verification` / `verified` / records of kind
  `verification`, `verified`, `verification_result`, `definition_of_done`,
  `dod` record. A completed bot answer is shown as "Resposta do bot (não
  verificada)".
- Handoffs/reassignments come from records of kind `handoff`, `reassignment`,
  `reassign`, `transfer`, `delegation`; legacy `source_task_id`/`source_bot_id`
  payloads are resolved through `tasks`.

### `GET /api/bot-groups/{group_id}/messages`

Each message may carry `run_id` and `seq`. `run_id` on the latest user message
anchors the visible execution. Without either field the UI falls back to the
newest active run and labels a room with history but no run as
"Sem execução registada" (not "Em espera", and not a fabricated terminal state).

### `POST /api/bot-groups/{group_id}/messages` (SSE)

Every frame may carry `run_id` and `seq`; the relay must preserve the runtime's
`(run_id, seq)` order. The UI accepts these types and ignores unknown ones:

- `user_message`, `agent_started`, `token`, `agent_message`, `agent_error`
- `run_status` / `run_state` / `status` / `state` (fields `state` or `status`)
- `done` (`status` and optional `reason`)
- `error` / `group_error`

Duplicate or out-of-order `(run_id, seq)` frames are dropped before they reach
the transcript or the partial token text. Frames without an envelope are
legacy and stay in arrival order. A dropped connection is reported as
"Ligação interrompida"; it does not set a failed run. The persisted messages
and `/runs` response are re-read afterwards and are the authority.

## Implemented fallbacks

| Backend response | UI behaviour |
|---|---|
| `run_id` + `state` present | state derived from that exact run |
| `run_id` present, run not in `/runs` yet | no old run is substituted; stream state/"A iniciar" is shown |
| `execution_engine` missing | engine shown as "Motor não indicado" |
| `state` missing | uses explicit `status` |
| `seq` missing | legacy arrival order, messages still deduplicated by id |
| `/runs` fails after a reload | keeps the previous snapshot; otherwise "Estado indisponível" |
| terminal room reload | "Concluída"/"Falhou"/"Cancelada"/"Bloqueada"/"A retomar" from the run, never "Em espera" |
| no run record at all but history exists | "Sem execução registada" (no invented outcome) |
| verification absent | "Sem verificação registada. A resposta de um bot é uma proposta, não prova de conclusão." |

## Selectors used by the draft E2E

| Purpose | Selector |
|---|---|
| open groups | `getByRole("button", { name: "Conversas de grupo" })` |
| group list | `getByRole("region", { name: "Grupos de bots" })` |
| group row | `getByRole("button", { name: /<group name>|participantes/ })` |
| room state (aria-live) | `getByTestId("room-state")` |
| run card | `getByTestId("run-card")` |
| run state | `getByTestId("run-state")` / `[data-run-state]` |
| verification block | `getByTestId("run-verification")` |
| composer | `getByRole("textbox", { name: "Mensagem para o grupo" })` |
| send | `getByRole("button", { name: "Enviar ao grupo" })` |
| stop | `getByRole("button", { name: "Pedir paragem do grupo" })` |
| group runs (context) | `getByRole("button", { name: /Execuções de equipa/ })` |
| runs dialog state | `getByTestId("group-run-state")` |

## Draft E2E spec (real backend, no route mocks)

Move this into `frontend/e2e/group-runtime-closeout.spec.ts` only when Agent 4
integrates it. It requires `NEXUS_E2E_GROUP` (the exact group name) and the real
`frontend/.env.local` credentials already used by `global-setup.ts`.

```ts
import { expect, test } from "@playwright/test";

const GROUP = process.env.NEXUS_E2E_GROUP ?? "";
const TERMINAL = /Concluída|Falhou|Cancelada|Bloqueada|Interrompida|Expirada/;

async function openGroup(page: import("@playwright/test").Page) {
  await page.goto("/bots");
  await page.getByRole("button", { name: "Conversas de grupo" }).click();
  const list = page.getByRole("region", { name: "Grupos de bots" });
  await list.getByRole("button", { name: new RegExp(GROUP) }).click();
  await expect(page.getByRole("textbox", { name: "Mensagem para o grupo" })).toBeVisible();
}

async function roomState(page: import("@playwright/test").Page) {
  return (await page.getByTestId("room-state").textContent())?.trim() ?? "";
}

test.describe("group composer runtime", () => {
  test.skip(!GROUP, "NEXUS_E2E_GROUP is required for the real-backend run");

  test("terminal state and verified content survive reload", async ({ page }) => {
    await openGroup(page);
    if ((await roomState(page)) === "Em espera" || (await roomState(page)) === "Sem execução registada") {
      await page.getByRole("textbox", { name: "Mensagem para o grupo" }).fill(
        "Responde apenas OK, sem ferramentas. Este pedido faz parte do closeout do compositor.",
      );
      await page.getByRole("button", { name: "Enviar ao grupo" }).click();
    }
    await expect.poll(() => roomState(page), { timeout: 180_000 }).toMatch(TERMINAL);
    const terminal = await roomState(page);
    await page.reload();
    await openGroup(page);
    await expect.poll(() => roomState(page), { timeout: 60_000 }).toBe(terminal);
    await expect(page.getByTestId("run-card")).toBeVisible();
    await expect(page.getByTestId("run-verification")).toBeVisible();
    await page.screenshot({ path: "test-results/group-runtime-terminal.png", fullPage: true });
  });

  test("reload during execution keeps the run and finishes without a reset", async ({ page }) => {
    await openGroup(page);
    await page.getByRole("textbox", { name: "Mensagem para o grupo" }).fill(
      "Analisa o estado do projeto e responde de forma curta. Este pedido faz parte do closeout.",
    );
    await page.getByRole("button", { name: "Enviar ao grupo" }).click();
    await expect.poll(() => roomState(page), { timeout: 30_000 }).toMatch(/Em execução|Em pausa|A retomar|A verificar/);
    const runId = await page.getByTestId("run-card").getAttribute("data-run-id");
    await page.reload();
    await openGroup(page);
    await expect(page.getByTestId("run-card")).toHaveAttribute("data-run-id", runId ?? "");
    await expect.poll(() => roomState(page), { timeout: 180_000 }).toMatch(TERMINAL);
    await expect(page.getByTestId("run-card")).toBeVisible();
  });

  test("stop asks for cancellation and resume is only offered by the run", async ({ page }) => {
    await openGroup(page);
    const state = await roomState(page);
    if (/Em execução|A planear|A verificar/.test(state)) {
      await page.getByRole("button", { name: "Pedir paragem do grupo" }).click();
      await expect.poll(() => roomState(page), { timeout: 30_000 }).toMatch(/A cancelar|Cancelada|Interrompida|Falhou/);
    }
    const resume = page.getByRole("button", { name: "Retomar" });
    if (await resume.count()) {
      await resume.first().click();
      await expect.poll(() => roomState(page), { timeout: 60_000 }).toMatch(/A retomar|Em execução|Concluída|Falhou/);
    }
  });
});
```
