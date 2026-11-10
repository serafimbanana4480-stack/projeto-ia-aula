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

test.describe("bot chat v2", () => {
  test("abre um bot, expande a ferramenta e mantém o compositor", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/bots");
    await page.getByRole("button", { name: /FORGE/ }).click();
    await expect(page.getByText("Inferência não verificada")).toBeVisible();
    await expect(page.locator("[data-sigil='forge']").first()).toBeVisible();
    await expect(page.locator("[data-sigil='forge']").first()).toHaveText("");
    await expect(page.getByText("parse(input: string)")).toBeVisible();
    await page.getByText("Atividade · 1 chamada").click();
    await expect(page.getByText("read_file")).toBeVisible();
    await expect(page.getByText("src/parser.ts").first()).toBeVisible();
    const composer = page.getByRole("textbox", { name: "Mensagem" });
    await expect(composer).toBeEnabled();
    await composer.fill("não enviar");
    await expect(page.getByRole("button", { name: "Enviar mensagem" })).toBeEnabled();
    await shot(page, "bot-1440x900");
    await page.setViewportSize({ width: 1920, height: 1080 });
    await shot(page, "bot-1920x1080");
    await page.setViewportSize({ width: 768, height: 1024 });
    await shot(page, "bot-768x1024");
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("button", { name: "Voltar às conversas" })).toBeVisible();
    await expect(composer).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(overflow).toBeFalsy();
    await shot(page, "bot-390x844");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("abre um grupo, o painel de contexto e a gaveta móvel", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openGroup(page, /^123/);
    await expect(page.getByTestId("group-incident")).toHaveCount(1);
    await expect(page.getByText("4 ocorrências")).toBeVisible();
    await expect(page.getByLabel("Quem está a fazer o quê")).toBeVisible();
    await page.getByRole("tab", { name: "Ficheiros" }).click();
    await expect(page.getByRole("tabpanel", { name: "Ficheiros" })).toContainText("src/parser.ts");
    await page.getByRole("tab", { name: "Ferramentas" }).click();
    await expect(page.getByRole("tabpanel", { name: "Ferramentas" })).toContainText("read_file");
    await page.getByRole("tab", { name: "Eventos" }).click();
    await expect(page.getByRole("tabpanel", { name: "Eventos" })).toContainText("fail-call");
    await page.getByRole("tab", { name: "Plano" }).click();
    await expect(page.getByRole("button", { name: /Execuções de equipa com leitura/ })).toBeVisible();
    await page.getByRole("tab", { name: "Participantes" }).click();
    await expect(page.getByRole("tabpanel", { name: "Participantes" })).toContainText("FORGE");
    await page.getByRole("button", { name: "Fechar contexto" }).click();
    await expect(page.getByRole("complementary", { name: "Contexto do grupo" })).toHaveCount(0);
    await page.getByRole("button", { name: "Abrir painel de contexto" }).click();
    await expect(page.getByRole("complementary", { name: "Contexto do grupo" })).toBeVisible();
    await shot(page, "group-context-1440x900");

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("button", { name: "Abrir lista de grupos" })).toBeVisible();
    await page.getByRole("button", { name: "Abrir lista de grupos" }).click();
    await expect(page.getByRole("region", { name: "Grupos de bots" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Fechar lista de grupos" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(overflow).toBeFalsy();
    await shot(page, "group-drawer-390x844");
  });

  test("enviar fica no fixture e não contacta um provider", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openGroup(page, /Planeamento/);
    const box = page.getByRole("textbox", { name: "Mensagem para o grupo" });
    await expect(box).toBeEnabled();
    await box.fill("@Fo");
    await expect(page.getByRole("listbox", { name: "Mencionar participante" })).toBeVisible();
    await page.getByRole("option", { name: /FORGE/ }).click();
    await expect(box).toHaveValue("@FORGE ");
    await box.fill("olá, sem provider");
    await page.getByRole("button", { name: "Enviar ao grupo" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "nenhum provider foi contactado" })).toBeVisible();
    await expect(box).toHaveValue("olá, sem provider");
  });

  test("mostra colaboração real numa execução concluída e noutra em curso", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openGroup(page, /Revisão concluída/);
    await expect(page.getByText("FORGE passou a Debugger")).toBeVisible();
    await expect(page.getByText("Resultado").first()).toBeVisible();
    await expect(page.getByText("As análises anteriores seguem como dados não verificados").first()).toBeVisible();
    await shot(page, "group-done-1440x900");
    await page.setViewportSize({ width: 1920, height: 1080 });
    await shot(page, "group-done-1920x1080");

    await page.setViewportSize({ width: 1440, height: 900 });
    await openGroup(page, /Revisão em curso/);
    await expect(page.getByText("Em execução", { exact: true })).toBeVisible();
    await expect(page.getByText("A executar")).toBeVisible();
    await expect(page.getByText("À espera")).toBeVisible();
    await shot(page, "group-running-1440x900");
  });
});
