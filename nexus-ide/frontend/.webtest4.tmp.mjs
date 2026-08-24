import { chromium } from "playwright";
const OUT = "C:/Users/rodri/AppData/Local/Temp/opencode/shots";
const log = (...a) => console.log("[wt4]", ...a);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));

await page.goto("http://localhost:3000/", { waitUntil: "domcontentloaded", timeout: 120_000 });
for (let i = 0; i < 15; i++) {
  if (await page.locator("textarea").count()) break;
  await page.waitForTimeout(1000);
}
await page.waitForTimeout(3000);

// 1. Model selector dropdown in chat header
try {
  // the header has a mode dropdown "Auto" and possibly a model chip; open the one with chevron near top
  const candidates = page.locator("header button, div[class*=header] button");
  const n = await candidates.count();
  log("header buttons:", n);
  // find button containing 'Auto' text (mode) — model selector may be separate; try clicking text=Auto first
  await page.locator("button", { hasText: "Auto" }).first().click({ timeout: 4000 });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/20-mode-dropdown.png` });
  log("mode dropdown saved");
  await page.keyboard.press("Escape");
} catch (e) { log("mode dropdown skip:", String(e).slice(0, 100)); }

// 2. Models page
await page.goto("http://localhost:3000/models", { waitUntil: "networkidle", timeout: 90_000 }).catch(() => {});
await page.waitForTimeout(5000);
await page.screenshot({ path: `${OUT}/21-models-page.png`, fullPage: false });
log("models page saved:", page.url());

// 3. Sessions (Conversas) panel
await page.goto("http://localhost:3000/", { waitUntil: "networkidle", timeout: 90_000 }).catch(() => {});
await page.waitForTimeout(3000);
try {
  await page.locator("button", { hasText: "Conversas" }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/22-sessions.png` });
  log("sessions saved");
} catch (e) { log("sessions skip:", String(e).slice(0, 100)); }

log("errors:", errors.length, errors.slice(0, 4));
await browser.close();
