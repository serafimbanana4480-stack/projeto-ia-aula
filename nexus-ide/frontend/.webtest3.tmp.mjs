import { chromium } from "playwright";
const OUT = "C:/Users/rodri/AppData/Local/Temp/opencode/shots";
const log = (...a) => console.log("[wt3]", ...a);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));

async function ensureLogin() {
  await page.goto("http://localhost:3000/", { waitUntil: "domcontentloaded", timeout: 120_000 });
  // wait for either chat textarea or login form
  for (let i = 0; i < 15; i++) {
    if (await page.locator("textarea").count()) return "chat";
    if (page.url().includes("/login")) break;
    await page.waitForTimeout(1000);
  }
  if (!page.url().includes("/login")) await page.goto("http://localhost:3000/login", { waitUntil: "networkidle" });
  // auto-login may kick in; wait for it
  for (let i = 0; i < 12; i++) {
    if (!(await page.locator("#email").count())) return "chat"; // navigated away
    await page.waitForTimeout(1000);
  }
  // manual login with up to 3 attempts
  for (let a = 0; a < 3; a++) {
    try {
      await page.fill("#email", "admin@nexus-ide.com");
      await page.fill("#password", "admin123");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/api/auth/login"), { timeout: 30_000 }),
        page.click('button[type="submit"]'),
      ]).then(([r]) => log("login resp:", r?.status()));
      await page.waitForURL((u) => !String(u).includes("/login"), { timeout: 20_000 });
      return "chat";
    } catch (e) {
      log("login attempt failed:", String(e).slice(0, 80));
      await page.waitForTimeout(4000);
    }
  }
  await page.screenshot({ path: OUT + "/09-login-fail.png" }); throw new Error("could not login");
}

const where = await ensureLogin();
log("where:", where, page.url()); await page.screenshot({ path: OUT + "/09-after-login.png" });
await page.waitForSelector("textarea", { timeout: 30_000 });
await page.waitForTimeout(4000);

const textarea = page.locator("textarea").first();
await textarea.fill("Lista os ficheiros do diretorio atual e diz quantos ha no total.");
await textarea.press("Enter");
log("sent");

let toolSeen = false;
for (let i = 0; i < 70; i++) {
  await page.waitForTimeout(2000);
  const timeline = await page.locator('[data-testid="run-timeline-toggle"]').count();
  if (!toolSeen && timeline > 0) {
    toolSeen = true;
    try {
      await page.locator('[data-testid="run-timeline-toggle"]').last().click({ timeout: 3000 });
      await page.waitForTimeout(900);
      await page.locator('[data-testid="run-step"]').last().scrollIntoViewIfNeeded().catch(() => {});
      await page.screenshot({ path: `${OUT}/10-timeline-open.png` });
      log("timeline screenshot saved (steps:", await page.locator('[data-testid="run-step"]').count(), ")");
    } catch (e) { log("timeline expand fail:", String(e).slice(0, 80)); }
  }
  const live = await page.locator("text=ao vivo").count();
  const thinking = await page.locator("text=a pensar").count();
  if (i > 8 && live === 0 && thinking === 0) break;
}
await page.waitForTimeout(2000);
await page.evaluate(() => {
  const els = Array.from(document.querySelectorAll("div")).filter((d) => d.scrollHeight > d.clientHeight + 80);
  els.forEach((e) => (e.scrollTop = e.scrollHeight));
});
await page.waitForTimeout(1000);
await page.screenshot({ path: `${OUT}/11-final-bottom.png` });
log("final saved. toolSeen:", toolSeen, "errors:", errors.length, errors.slice(0, 4));
await browser.close();
