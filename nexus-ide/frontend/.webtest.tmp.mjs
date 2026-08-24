import { chromium } from "playwright";
import fs from "fs";

const OUT = "C:/Users/rodri/AppData/Local/Temp/opencode/shots";
fs.mkdirSync(OUT, { recursive: true });
const BASE = "http://localhost:3000";
const log = (...a) => console.log("[webtest]", ...a);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => {
  if (m.type() === "error") errors.push(`console: ${m.text().slice(0, 240)}`);
});
page.on("response", (r) => {
  if (r.url().includes("/api/auth/")) log("auth api:", r.status(), r.url());
});

await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 120_000 });
await page.waitForTimeout(3000);
if (page.url().includes("/login")) {
  await page.fill("#email", "admin@nexus-ide.com");
  await page.fill("#password", "admin123");
  const [resp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/auth/login"), { timeout: 45_000 }).catch(() => null),
    page.click('button[type="submit"]'),
  ]);
  if (resp) log("login status:", resp.status());
  // wait for redirect away from /login
  try {
    await page.waitForURL((u) => !String(u).includes("/login"), { timeout: 30_000 });
  } catch {
    await page.screenshot({ path: `${OUT}/login-stuck.png` });
    const err = await page.locator("text=/Sessão expirada|Erro|erro/i").allTextContents();
    log("LOGIN STUCK. visible errors:", err.slice(0, 3));
  }
}
log("url now:", page.url());
await page.waitForTimeout(8000);
await page.screenshot({ path: `${OUT}/02-chat-initial.png` });
log("chat initial saved");

// textarea
await page.waitForSelector("textarea", { timeout: 30_000 });
const textarea = page.locator("textarea").first();
await textarea.fill("Lista os ficheiros do diretorio atual e diz quantos ha no total.");
await textarea.press("Enter");
log("message sent");
let sawTool = false;
for (let i = 0; i < 30; i++) {
  await page.waitForTimeout(2500);
  if (!sawTool) {
    const t = await page.locator("text=a usar ferramenta").count();
    if (t > 0) {
      sawTool = true;
      await page.screenshot({ path: `${OUT}/03-tool-inflight.png` });
      log("tool indicator visible — screenshot saved");
    }
  }
  const live = await page.locator("text=ao vivo").count();
  if (live === 0 && i > 3) break;
}
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/04-final-answer.png` });
log("final saved. sawTool:", sawTool);
log("errors:", errors.length);
errors.slice(0, 8).forEach((e) => log("ERR:", e));
await browser.close();
