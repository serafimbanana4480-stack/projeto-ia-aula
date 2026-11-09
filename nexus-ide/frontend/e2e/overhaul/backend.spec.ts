import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const shotsDir = process.env.OVERHAUL_SHOTS_DIR;

async function shot(page: Page, name: string) {
  if (!shotsDir) return;
  fs.mkdirSync(shotsDir, { recursive: true });
  await page.screenshot({ path: path.join(shotsDir, `${name}.png`) });
}

const PAGES: Array<{ path: string; heading?: string; shot: string }> = [
  { path: "/dashboard", heading: "Painel de Operações", shot: "real-dashboard-1440x900" },
  { path: "/projects", heading: "Projetos", shot: "real-projects-1440x900" },
  { path: "/dashboard/tasks", shot: "real-tasks-1440x900" },
  { path: "/settings", shot: "real-settings-1440x900" },
  { path: "/bots", shot: "real-bots-1440x900" },
  { path: "/mcp", heading: "Ligações MCP", shot: "real-mcp-1440x900" },
  { path: "/scraping", heading: "Recolha web", shot: "real-scraping-1440x900" },
  { path: "/nexus/hitl", heading: "Aprovações", shot: "real-approvals-1440x900" },
  { path: "/documents", heading: "Documentos", shot: "real-documents-1440x900" },
  { path: "/search", heading: "Pesquisa", shot: "real-search-1440x900" },
  { path: "/swarm", shot: "real-swarm-1440x900" },
  { path: "/tools", shot: "real-tools-1440x900" },
  { path: "/analytics", shot: "real-metrics-1440x900" },
  { path: "/editor", shot: "real-editor-1440x900" },
];

test("frontend contra o FastAPI real, sem pedido a provider", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const entry of PAGES) {
    await page.goto(entry.path);
    await expect(page.locator('aside[aria-label="Navegação principal"]')).toHaveCount(1);
    if (entry.heading) {
      await expect(page.getByRole("heading", { name: entry.heading, exact: true })).toBeVisible();
    }
    await shot(page, entry.shot);
  }

  await page.goto("/");
  await expect(page.locator('aside[aria-label="Navegação principal"]')).toHaveCount(1);
  const composer = page.getByRole("textbox", { name: "Mensagem para o NEXUS" });
  await expect(composer).toBeVisible();
  await expect(page.getByTestId("composer-availability")).toBeVisible();
  await page.getByRole("button", { name: /Modelo:/ }).click();
  await expect(page.getByRole("dialog", { name: "Selecionar modelo" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Enviar mensagem" })).toBeDisabled();
  await shot(page, "real-chat-1440x900");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/nexus/hitl");
  await expect(page.getByRole("button", { name: "Abrir menu" })).toBeVisible();
  const navRight = await page.locator("#nexus-primary-navigation").evaluate((node) => node.getBoundingClientRect().right);
  expect(navRight).toBeLessThanOrEqual(1);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBeFalsy();
  await shot(page, "real-approvals-390x844");

  expect(errors, errors.join("\n")).toEqual([]);
});
