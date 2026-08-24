import { chromium } from "playwright";
const OUT = "C:/Users/rodri/AppData/Local/Temp/opencode/shots";
const log = (...a) => console.log("[wt5]", ...a);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));

async function ensureChat() {
  for (let attempt = 0; attempt < 4; attempt++) {
    await page.goto("http://localhost:3000/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    for (let i = 0; i < 12; i++) {
      if (await page.locator("textarea").count()) return true;
      if (page.url().includes("/login")) break;
      await page.waitForTimeout(1000);
    }
    if (page.url().includes("/login")) {
      // wait for auto-login, then manual fallback
      for (let i = 0; i < 10; i++) {
        if (!(await page.locator("#email").count().catch(() => 0))) break;
        await page.waitForTimeout(1000);
      }
      if (page.url().includes("/login")) {
        try {
          await page.fill("#email", "admin@nexus-ide.com");
          await page.fill("#password", "admin123");
          await page.click('button[type="submit"]');
          await page.waitForURL((u) => !String(u).includes("/login"), { timeout: 20_000 });
        } catch { log("manual login retry", attempt); }
      }
    }
  }
  return !!(await page.locator("textarea").count());
}

const ok = await ensureChat();
log("chat ready:", ok);
await page.waitForTimeout(3000);

// Model selector: find the header chip. From screenshots, top bar has "Auto" dropdown and a model area.
const autoBtn = page.getByRole("button", { name: /Auto/i }).first();
if (await autoBtn.count()) {
  await autoBtn.click({ timeout: 5000 }).catch((e) => log("auto click fail", String(e).slice(0, 80)));
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/20-header-dropdown.png` });
  log("header dropdown saved");
  await page.keyboard.press("Escape");
}

// Models page with re-login
for (let attempt = 0; attempt < 3; attempt++) {
  await page.goto("http://localhost:3000/models", { waitUntil: "networkidle", timeout: 90_000 }).catch(() => {});
  await page.waitForTimeout(4000);
  if (!page.url().includes("/login")) break;
  log("models redirected to login, re-authing");
  await ensureChat();
}
await page.screenshot({ path: `${OUT}/21-models-page.png` });
log("models page:", page.url());

// back to chat, open Conversas
await ensureChat();
await page.waitForTimeout(2000);
const conv = page.getByRole("button", { name: /Conversas/i }).first();
if (await conv.count()) {
  await conv.click({ timeout: 5000 }).catch((e) => log("conv fail", String(e).slice(0, 80)));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/22-sessions.png` });
  log("sessions saved");
}
log("errors:", errors.length, errors.slice(0, 4));
await browser.close();
