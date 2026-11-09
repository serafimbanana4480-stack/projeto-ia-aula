import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const shotsDir = process.env.CHAT_V2_DIR
  ?? path.join("output", "playwright", "overhaul-2026-11-09", "chat-v2", "before");

const viewports = [
  { width: 390, height: 844, name: "390x844" },
  { width: 768, height: 1024, name: "768x1024" },
  { width: 1440, height: 900, name: "1440x900" },
  { width: 1920, height: 1080, name: "1920x1080" },
] as const;

async function shot(page: Page, name: string) {
  fs.mkdirSync(shotsDir, { recursive: true });
  await page.screenshot({ path: path.join(shotsDir, `${name}.png`), fullPage: false });
}

async function openMainChat(page: Page) {
  await page.goto("/");
  await expect(page.getByText("Parser").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("textbox", { name: "Mensagem para o NEXUS" })).toBeVisible();
    await expect.poll(async () => {
      await page.getByTestId("messages").evaluate((node) => { node.scrollTop = 0; });
      return page.getByText("Explica o parser em markdown.").isVisible();
    }).toBe(true);
  }

test("chat principal antes e depois da conversa nova", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await openMainChat(page);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await shot(page, `main-chat-${viewport.name}`);
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await openMainChat(page);
  await page.getByRole("button", { name: "Iniciar nova conversa" }).click();
  await expect(page.getByRole("heading", { name: /O que vamos construir|Trabalhar em/ })).toBeVisible();
  await shot(page, "main-chat-empty-1440x900");

  expect(errors, errors.join("\n")).toEqual([]);
});
