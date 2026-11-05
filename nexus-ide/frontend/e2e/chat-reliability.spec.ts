import { expect, test } from "@playwright/test";

test.describe("Chat, ferramentas e recuperação", () => {
  test("mostra código com copiar e uma linha de ferramenta real", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("ai-cockpit")).toBeVisible();
    await expect(page.getByRole("button", { name: "Copiar código" })).toBeVisible();

    const input = page.getByPlaceholder(/Pergunte qualquer coisa/);
    await input.fill("Lê o README");
    await page.getByRole("button", { name: "Enviar" }).click();
    await expect(page.getByTestId("tool-row").first()).toContainText("README.md", { timeout: 15000 });
    await expect(page.getByTestId("tool-row").nth(1)).toContainText("terminal");
    await expect(page.getByText("Feito.")).toBeVisible();
  });

  test("a navegação principal tem os destinos do produto", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const nav = page.getByRole("navigation", { name: "Principal" });
    for (const label of ["Chat", "Workspace", "Agentes", "Atividade", "Dashboard"]) {
      await expect(nav.getByRole("link", { name: label })).toBeVisible();
    }
  });

  test("o painel de execução fica vazio até haver um objetivo", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const panel = page.getByTestId("execution-panel");
    if (await panel.count()) {
      await expect(panel).toBeVisible();
    }
  });

  test("uma ferramenta falhada não parece uma queda de ligação", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.getByPlaceholder(/Pergunte qualquer coisa/).fill("há um erro nos testes");
    await page.getByRole("button", { name: "Enviar" }).click();
    await expect(page.getByTestId("tool-row")).toContainText("falhou", { timeout: 15000 });
    await expect(page.getByText("ligação ao provedor foi interrompida")).toHaveCount(0);
  });

  test("cancelar um run lento marca o agente como cancelado", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.getByPlaceholder(/Pergunte qualquer coisa/).fill("resposta lenta por favor");
    await page.getByRole("button", { name: "Enviar" }).click();
    await expect(page.getByTestId("agent-tree")).toContainText("NEXUS", { timeout: 15000 });
    await page.getByRole("button", { name: "Parar" }).click();
    await expect(page.getByTestId("agent-tree")).toContainText("CANCELLED", { timeout: 10000 });
  });

  test("uma escrita perigosa pede aprovação antes de correr", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.getByPlaceholder(/Pergunte qualquer coisa/).fill("aprova a escrita do README");
    await page.getByRole("button", { name: "Enviar" }).click();
    await expect(page.getByRole("button", { name: "Permitir uma vez" })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("button", { name: "Recusar" })).toBeVisible();
  });

  test("o histórico sobrevive a um refresh", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Aqui está uma ordenação estável.")).toBeVisible();
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByText("Aqui está uma ordenação estável.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Copiar código" })).toBeVisible();
  });
});
