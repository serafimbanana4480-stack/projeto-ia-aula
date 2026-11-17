import fs from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * Browser proof for the group composer -> primary runtime path.
 *
 * Unlike the overhaul fixtures, this spec talks to the real backend and the
 * real SSE stream.  It is opt-in because it needs disposable backend state
 * (`NEXUS_GROUP_E2E=1`) and a scripted loopback provider started by the
 * closeout harness.  It never mocks the UI state or the event stream.
 */

const apiUrl = (process.env.NEXUS_E2E_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const evidenceDir = process.env.NEXUS_E2E_EVIDENCE_DIR || "";
const projectName = process.env.NEXUS_E2E_PROJECT_NAME || "";

function shotPath(name: string): string | null {
  if (!evidenceDir) return null;
  fs.mkdirSync(evidenceDir, { recursive: true });
  return path.join(evidenceDir, `${name}.png`);
}

async function tokenFromPage(page: Page): Promise<string> {
  await page.goto("/");
  const token = await page.evaluate(() => window.localStorage.getItem("nexus.access_token"));
  if (!token) throw new Error("no nexus.access_token in the authenticated storage state");
  return token;
}

async function createBotsAndGroup(api: APIRequestContext, token: string) {
  const headers = { Authorization: `Bearer ${token}` };
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 10_000)}`;
  const bots: Array<{ id: string; name: string }> = [];
  for (const suffix of ["Leitor", "Revisor"]) {
    const response = await api.post("/api/bots", {
      headers,
      data: {
        name: `E2E ${suffix} ${stamp}`,
        description: "Leitura e revisão determinística",
        instructions: "Responde de forma factual.",
        provider: "ollama",
        model: "scripted:latest",
      },
    });
    expect(response.ok(), `create bot failed: ${response.status()} ${await response.text()}`).toBeTruthy();
    const body = await response.json();
    bots.push({ id: body.id, name: body.name });
  }
  const groupResponse = await api.post("/api/bot-groups", {
    headers,
    data: { name: `E2E grupo ${stamp}`, bot_ids: bots.map((bot) => bot.id) },
  });
  expect(
    groupResponse.ok(),
    `create group failed: ${groupResponse.status()} ${await groupResponse.text()}`,
  ).toBeTruthy();
  const group = await groupResponse.json();
  return { group, bots };
}

async function openGroup(page: Page, groupName: string) {
  await page.goto("/bots", { waitUntil: "domcontentloaded" });
  const groupButton = page.getByRole("button", { name: "Conversas de grupo" });
  if (await groupButton.count()) await groupButton.click();
  const row = page.getByRole("button", { name: new RegExp(groupName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) });
  await expect(row).toBeVisible({ timeout: 20_000 });
  await row.click();
  await expect(page.getByLabel("Histórico do grupo")).toBeVisible({ timeout: 20_000 });
  if (projectName) {
    const project = page.getByLabel("Projeto do grupo");
    await expect(project).toContainText(projectName, { timeout: 20_000 });
    await project.selectOption({ label: projectName });
  }
}

test.describe("group composer primary runtime", () => {
  test.skip(process.env.NEXUS_GROUP_E2E !== "1", "set NEXUS_GROUP_E2E=1 to run against the disposable real backend");

  test("one composer message persists one verified run across a reload", async ({ page, request }) => {
    const token = await tokenFromPage(page);
    const { group } = await createBotsAndGroup(request, token);

    await openGroup(page, group.name);
    const composer = page.getByRole("textbox", { name: "Mensagem para o grupo" });
    await expect(composer).toBeEnabled({ timeout: 20_000 });
    const marker = `E2E-RESPOSTA-${Date.now()}`;
    await composer.fill(`Diz exatamente ${marker}`);
    await page.getByRole("button", { name: "Enviar ao grupo" }).click();

    const answer = page.locator("article").filter({ hasText: marker });
    await expect(answer.last()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("room-state")).toHaveText(/Conclu/, { timeout: 60_000 });
    const runCard = page.getByTestId("run-card");
    await expect(runCard).toBeVisible();
    await expect(runCard).toHaveAttribute("data-run-state", "completed");
    const runId = await runCard.getAttribute("data-run-id");
    expect(runId).toBeTruthy();

    const before = await page.locator("article").count();
    const screenshot = shotPath("group-runtime-completed");
    if (screenshot) await page.screenshot({ path: screenshot, fullPage: true });

    await page.reload({ waitUntil: "domcontentloaded" });
    await openGroup(page, group.name);
    await expect(
      page.locator("article").filter({ hasText: marker }).last(),
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("room-state")).toHaveText(/Conclu/, { timeout: 20_000 });
    await expect(page.locator("article")).toHaveCount(before);
    await expect(page.getByTestId("run-card")).toHaveAttribute("data-run-id", runId!);

    if (evidenceDir) {
      fs.writeFileSync(
        path.join(evidenceDir, "browser-reload.json"),
        JSON.stringify(
          { runId, marker, articles: before, group: group.id, groupName: group.name },
          null,
          2,
        ),
        "utf-8",
      );
    }
  });

  test("one composer message executes a real tool and shows the workspace result", async ({ page, request }) => {
    const token = await tokenFromPage(page);
    const { group } = await createBotsAndGroup(request, token);

    await openGroup(page, group.name);
    const composer = page.getByRole("textbox", { name: "Mensagem para o grupo" });
    await expect(composer).toBeEnabled({ timeout: 20_000 });
    const marker = `E2E-TOOL-${Date.now()}`;
    await composer.fill(`Lê o ficheiro canary.txt do projeto e devolve o token exato. ${marker}`);
    await page.getByRole("button", { name: "Enviar ao grupo" }).click();

    await expect(
      page.locator("article").filter({ hasText: "CANARY-BROWSER-7F3A" }).last(),
    ).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("room-state")).toHaveText(/Conclu/, { timeout: 90_000 });
    const runCard = page.getByTestId("run-card");
    await expect(runCard).toBeVisible();
    await expect(runCard).toHaveAttribute("data-run-state", "completed");
    await expect(runCard.getByText(/read_file/).first()).toBeVisible({ timeout: 20_000 });
    const runId = await runCard.getAttribute("data-run-id");
    expect(runId).toBeTruthy();
    const screenshot = shotPath("group-runtime-tool");
    if (screenshot) await page.screenshot({ path: screenshot, fullPage: true });

    if (evidenceDir) {
      fs.writeFileSync(
        path.join(evidenceDir, "browser-tool.json"),
        JSON.stringify({ runId, marker, group: group.id, groupName: group.name }, null, 2),
        "utf-8",
      );
    }
  });

  test("after a backend restart the reload shows the same completed run", async ({ page }) => {
    const groupId = process.env.NEXUS_E2E_REUSE_GROUP_ID;
    const groupName = process.env.NEXUS_E2E_REUSE_GROUP_NAME;
    const expectedRunId = process.env.NEXUS_E2E_EXPECT_RUN_ID;
    test.skip(!groupId || !groupName || !expectedRunId, "requires a run created by the reload scenario");

    await openGroup(page, groupName!);
    await expect(page.getByTestId("room-state")).toHaveText(/Conclu/, { timeout: 30_000 });
    const runCard = page.getByTestId("run-card");
    await expect(runCard).toHaveAttribute("data-run-id", expectedRunId!);
    await expect(runCard).toHaveAttribute("data-run-state", "completed");
    await expect(page.getByText(/CANARY-BROWSER-7F3A|Diz exatamente E2E-RESPOSTA-/).first()).toBeVisible();

    const screenshot = shotPath("group-runtime-after-restart");
    if (screenshot) await page.screenshot({ path: screenshot, fullPage: true });
    if (evidenceDir) {
      fs.writeFileSync(
        path.join(evidenceDir, "browser-restart.json"),
        JSON.stringify({ runId: expectedRunId, groupId, groupName }, null, 2),
        "utf-8",
      );
    }
  });
});
