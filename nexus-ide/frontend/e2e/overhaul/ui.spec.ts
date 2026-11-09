import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const shotsDir = process.env.OVERHAUL_SHOTS_DIR;

async function shot(page: Page, name: string) {
  if (!shotsDir) return;
  fs.mkdirSync(shotsDir, { recursive: true });
  await page.screenshot({ path: path.join(shotsDir, `${name}.png`) });
}

async function openGroup(page: Page, name: RegExp) {
  await page.goto("/bots");
  await page.getByRole("button", { name: "Conversas de grupo" }).click();
  await page.getByRole("button", { name }).click();
  await expect(page.getByLabel("Histórico do grupo")).toBeVisible();
}

test.describe("overhaul UI", () => {
  test("navegação, shell único e páginas principais", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width: 1440, height: 900 });

    await page.goto("/dashboard");
    await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();
    await shot(page, "dashboard-1440x900");

    await page.goto("/");
    await expect(page.getByText("Parser").first()).toBeVisible({ timeout: 30_000 });
    await shot(page, "chat-1440x900");

    await page.keyboard.press("Control+K");
    await expect(page.getByRole("dialog", { name: "Paleta de comandos" })).toBeVisible();
    await page.getByLabel("Filtrar páginas, projetos e bots").fill("Definições");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/settings/);
    await shot(page, "settings-1440x900");

    await page.goto("/projects");
    await expect(page.locator('aside[aria-label="Navegação principal"]')).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "Projetos" })).toHaveCount(1);
    await page.getByRole("button", { name: "Novo projeto" }).click();
    await expect(page.getByRole("heading", { name: "Criar projeto" })).toBeVisible();
    await page.getByRole("button", { name: "Cancelar" }).click();
    await shot(page, "projects-1440x900");

    await page.goto("/dashboard/tasks");
    await expect(page.getByText("Rever parser")).toBeVisible();
    await shot(page, "tasks-1440x900");

    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("bot individual, markdown e tool call", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/bots");
    await page.getByRole("button", { name: /FORGE/ }).click();
    await expect(page.getByText("Inferência não verificada")).toBeVisible();
    await expect(page.getByText("parse(input: string)")).toBeVisible();
    await page.getByText("Atividade · 1 chamada").click();
    await expect(page.getByText("read_file")).toBeVisible();
    const composer = page.getByRole("textbox", { name: "Mensagem" });
    await expect(composer).toBeEnabled();
    await composer.fill("não enviar");
    await expect(page.getByRole("button", { name: "Enviar mensagem" })).toBeEnabled();
    await shot(page, "bot-1440x900");
  });

  test("grupo com falha agrupada, contexto, scroll e viewports", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openGroup(page, /^123/);
    await expect(page.getByTestId("group-incident")).toHaveCount(1);
    await expect(page.getByText("4 ocorrências")).toBeVisible();
    await expect(page.getByText("FORGE · falhou")).toHaveCount(0);
    await page.getByRole("button", { name: "Detalhes técnicos" }).click();
    await expect(page.getByText(/FORGE · e1/)).toBeVisible();
    const history = page.getByLabel("Histórico do grupo");
    const scrollable = await history.evaluate((node) => node.scrollHeight > node.clientHeight);
    expect(scrollable).toBeTruthy();
    await history.evaluate((node) => {
      node.scrollTop = node.scrollHeight;
    });
    await expect(page.getByRole("complementary", { name: "Contexto do grupo" })).toBeVisible();
    await page.getByRole("button", { name: "Fechar contexto" }).click();
    await expect(page.getByRole("complementary", { name: "Contexto do grupo" })).toHaveCount(0);
    await page.getByRole("button", { name: "Abrir painel de contexto" }).click();
    const composer = page.getByRole("textbox", { name: "Mensagem para o grupo" });
    await expect(composer).toBeEnabled();
    await composer.fill("linha 1");
    await composer.press("Shift+Enter");
    await shot(page, "group-failed-1440x900");

    await page.setViewportSize({ width: 1920, height: 1080 });
    await shot(page, "group-failed-1920x1080");
    await page.getByRole("button", { name: "Fechar contexto" }).click();

    await page.setViewportSize({ width: 1024, height: 768 });
    await expect(page.getByRole("region", { name: "Grupos de bots" })).toBeVisible();
    const widthAt1024 = await history.evaluate((node) => node.getBoundingClientRect().width);
    expect(widthAt1024).toBeGreaterThan(360);
    await shot(page, "group-failed-1024x768");

    await page.setViewportSize({ width: 768, height: 1024 });
    await expect(page.getByRole("button", { name: "Abrir lista de grupos" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Abrir menu" })).toBeVisible();
    const navRightAt768 = await page.locator("#nexus-primary-navigation").evaluate((node) => node.getBoundingClientRect().right);
    expect(navRightAt768).toBeLessThanOrEqual(1);
    const widthAt768 = await history.evaluate((node) => node.getBoundingClientRect().width);
    expect(widthAt768).toBeGreaterThan(480);
    await shot(page, "group-failed-768x1024");

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("button", { name: "Abrir lista de grupos" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Abrir menu" })).toBeVisible();
    const navRightAt390 = await page.locator("#nexus-primary-navigation").evaluate((node) => node.getBoundingClientRect().right);
    expect(navRightAt390).toBeLessThanOrEqual(1);
    await expect(composer).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(overflow).toBeFalsy();
    await page.getByRole("button", { name: "Abrir lista de grupos" }).click();
    await expect(page.getByRole("button", { name: "Fechar lista de grupos" })).toBeVisible();
    await shot(page, "group-failed-390x844");

    await page.setViewportSize({ width: 1440, height: 900 });
    await openGroup(page, /Revisão em curso/);
    await expect(page.getByText("Em execução", { exact: true })).toBeVisible();
    await shot(page, "group-running-1440x900");

    await openGroup(page, /Planeamento/);
    await expect(page.getByText("Envia uma mensagem para iniciar")).toBeVisible();
    await shot(page, "group-idle-1440x900");
  });
});
