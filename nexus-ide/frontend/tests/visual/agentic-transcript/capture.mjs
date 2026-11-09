import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "@playwright/test";

const output = process.argv[2];
if (!output || !path.isAbsolute(output)) throw new Error("Expected a new absolute output directory");
await fs.mkdir(output); // Fails instead of overwriting an existing evidence directory.
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  page.setDefaultTimeout(12_000);
  page.on("pageerror", (error) => console.error("Browser error:", error.message));
  page.on("console", (message) => { if (message.type() === "error") console.error("Console:", message.text()); });
  await page.goto("http://127.0.0.1:3109/", { waitUntil: "networkidle" });
  await page.getByText("TESTE VISUAL", { exact: false }).waitFor();
  await page.getByTestId("transcript-tool").first().getByRole("button").click();
  await page.getByText("def example():", { exact: false }).first().waitFor();
  await page.screenshot({ path: path.join(output, "01-chat-fixture.png"), fullPage: true });
  await page.getByTestId("transcript-subagent").filter({ hasText: "CODER" }).click();
  const panel = page.getByTestId("subagent-panel");
  await panel.getByText("Vou ler o ficheiro.").waitFor();
  if (await panel.getByText("Dependência indisponível.").count()) throw new Error("Child data mixed");
  await page.screenshot({ path: path.join(output, "02-subagente-fixture.png"), fullPage: true });
  await panel.getByRole("button", { name: "DEBUGGER" }).click();
  await panel.getByText("Dependência indisponível.").waitFor();
  if (await panel.getByText("Vou ler o ficheiro.").count()) throw new Error("Child data mixed");
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("Bloqueado").waitFor();
  await page.screenshot({ path: path.join(output, "03-reload-fixture.png"), fullPage: true });
  console.log(`Visual fixture passed; screenshots: ${output}`);
} finally {
  await browser.close();
}
