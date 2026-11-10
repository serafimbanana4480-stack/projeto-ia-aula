import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const shotsDir = process.env.README_SHOTS_DIR
  ?? path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../docs/screenshots");

async function shot(page: Page, name: string) {
  fs.mkdirSync(shotsDir, { recursive: true });
  await page.screenshot({ path: path.join(shotsDir, `${name}.png`) });
}

async function openGroup(page: Page, name: RegExp) {
  await page.goto("/bots");
  await page.getByRole("button", { name: "Conversas de grupo" }).click();
  await page.getByRole("button", { name }).click();
  await expect(page.getByLabel("Histórico do grupo")).toBeVisible();
}

test.describe("readme screenshots", () => {
  test("captura o estado atual com o fixture local", async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 1440, height: 900 });

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Painel de Operações" })).toBeVisible();
    await shot(page, "dashboard-desktop");

    await page.goto("/");
    await expect(page.getByText("Parser").first()).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("chat-header").getByRole("button", { name: "Painel de contexto", exact: true }).click();
    await shot(page, "chat-desktop");

    await page.goto("/projects");
    await expect(page.getByRole("heading", { name: "Projetos" })).toBeVisible();
    await shot(page, "projects-desktop");

    await page.goto("/dashboard/tasks");
    await expect(page.getByText("Rever parser")).toBeVisible();
    await shot(page, "tasks-desktop");

    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Definições" })).toBeVisible();
    await shot(page, "settings-desktop");

    await page.goto("/bots");
    await page.getByRole("button", { name: /FORGE/ }).click();
    await expect(page.getByText("parse(input: string)")).toBeVisible();
    await page.getByText("Atividade · 1 chamada").click();
    await expect(page.getByText("read_file")).toBeVisible();
    await shot(page, "bot-desktop");

    await openGroup(page, /^123/);
    await expect(page.getByTestId("group-incident")).toHaveCount(1);
    await expect(page.getByText("4 ocorrências")).toBeVisible();
    await shot(page, "group-incident-desktop");

    await openGroup(page, /Revisão em curso/);
    await expect(page.getByText("Em execução", { exact: true })).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Contexto do grupo" })).toBeVisible();
    await shot(page, "group-running-desktop");
    await page.getByRole("tab", { name: "Ficheiros" }).click();
    await expect(page.getByRole("tabpanel", { name: "Ficheiros" })).toContainText("src/parser.ts");
    await shot(page, "group-context-desktop");

    await openGroup(page, /Revisão concluída/);
    await expect(page.getByText("FORGE passou a Debugger")).toBeVisible();
    await expect(page.getByText("Resultado").first()).toBeVisible();
    await shot(page, "group-done-desktop");

    await page.setViewportSize({ width: 1920, height: 1080 });
    await shot(page, "group-done-wide");

    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Painel de Operações" })).toBeVisible();
    await shot(page, "dashboard-tablet");
  });

  test("captura telemóvel", async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/bots");
    await page.getByRole("button", { name: /FORGE/ }).click();
    await expect(page.getByRole("button", { name: "Voltar às conversas" })).toBeVisible();
    await shot(page, "bot-mobile");
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Abrir menu" })).toBeVisible();
    await expect(page.getByText("Parser").first()).toBeVisible({ timeout: 30_000 });
    await shot(page, "chat-mobile");
  });
});
