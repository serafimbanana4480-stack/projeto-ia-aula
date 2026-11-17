import fs from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Composer v3 evidence. COMPOSER_SHOTS=before|after picks the folder.
 * The selectors stay on roles that both the previous and the slim composer expose.
 */
const phase = process.env.COMPOSER_SHOTS === "before" ? "before" : "after";
const shotsDir = path.join(process.cwd(), "output/playwright/composer-v3", phase);

const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

const multiline = [
  "Quero rever o parser.",
  "O ramo de parse() corta espaços.",
  "Falta o caso da string vazia.",
  "Confirma com um teste antes de alterar o ficheiro.",
].join("\n");

function ensureDir() {
  fs.mkdirSync(shotsDir, { recursive: true });
}

async function composerDock(page: Page): Promise<Locator> {
  const dock = page.getByTestId("composer-dock");
  if (await dock.count()) return dock.first();
  return page.locator(".nx-bot-composer").locator("xpath=ancestor::div[contains(@class,'border-t')][1]");
}

async function shoot(page: Page, room: string, state: string) {
  ensureDir();
  const dock = await composerDock(page);
  await expect(dock).toBeVisible();
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(dock).toBeVisible();
    const file = path.join(shotsDir, `${room}-${state}-${viewport.width}.png`);
    await dock.screenshot({ path: file });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

async function openBot(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/bots");
  await page.getByRole("button", { name: /FORGE/ }).click();
  const box = page.getByRole("textbox", { name: "Mensagem" });
  await expect(box).toBeEnabled();
  return box;
}

async function openGroup(page: Page, name: RegExp) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/bots");
  await page.getByRole("button", { name: "Conversas de grupo" }).click();
  await page.getByRole("button", { name }).click();
  await expect(page.getByLabel("Histórico do grupo")).toBeVisible();
  const box = page.getByRole("textbox", { name: "Mensagem para o grupo" });
  await expect(box).toBeVisible();
  return box;
}

test.describe("compositor v3", () => {
  test("bot: vazio, focado, várias linhas e a transmitir", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    const box = await openBot(page);
    await shoot(page, "bot", "empty");

    await box.click();
    await expect(box).toBeFocused();
    await shoot(page, "bot", "focused");

    await box.fill(multiline);
    await expect(box).toHaveValue(multiline);
    await shoot(page, "bot", "multiline");

    let release = () => {};
    await page.route("**/api/chat", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      await route.abort().catch(() => {});
    });
    await box.fill("a transmitir");
    const send = page.getByRole("button", { name: "Enviar mensagem" });
    await expect(send).toBeEnabled();
    await send.click();
    await expect(page.getByRole("button", { name: "Pedir paragem" })).toBeVisible();
    await shoot(page, "bot", "streaming");
    release();
    await page.unroute("**/api/chat").catch(() => {});

    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("grupo: vazio, focado, várias linhas e em execução", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    const box = await openGroup(page, /Planeamento/);
    await expect(box).toBeEnabled();
    await shoot(page, "group", "empty");

    await box.click();
    await expect(box).toBeFocused();
    await shoot(page, "group", "focused");

    await box.fill(multiline);
    await expect(box).toHaveValue(multiline);
    await shoot(page, "group", "multiline");

    await box.fill("@Fo");
    const menu = page.getByRole("listbox", { name: "Mencionar participante" });
    await expect(menu).toBeVisible();
    const dockBox = await (await composerDock(page)).boundingBox();
    const viewport = page.viewportSize() ?? { width: 1440, height: 900 };
    if (dockBox) {
      const x = Math.max(0, dockBox.x - 12);
      const y = Math.max(0, dockBox.y - 240);
      await page.screenshot({
        path: path.join(shotsDir, "group-mention-1440.png"),
        clip: {
          x,
          y,
          width: Math.min(dockBox.width + 24, viewport.width - x),
          height: Math.min(dockBox.height + Math.min(240, dockBox.y) + 12, viewport.height - y),
        },
      });
    }
    await page.keyboard.press("Escape");

    const running = await openGroup(page, /Revisão em curso/);
    await expect(page.getByRole("button", { name: "Pedir paragem do grupo" })).toBeVisible();
    await expect(running).toBeEnabled();
    await shoot(page, "group", "streaming");

    expect(errors, errors.join("\n")).toEqual([]);
  });
});
