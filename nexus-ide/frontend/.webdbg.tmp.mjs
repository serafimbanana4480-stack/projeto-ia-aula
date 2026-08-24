import { chromium } from "playwright";
const BASE = "http://localhost:3000";
const log = (...a) => console.log("[dbg]", ...a);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
page.on("request", (r) => { if (r.url().includes(":8000")) log("REQ:", r.method(), r.url()); });
page.on("response", (r) => { if (r.url().includes(":8000")) log("RES:", r.status(), r.url()); });
page.on("console", (m) => log("console[" + m.type() + "]:", m.text().slice(0, 160)));
page.on("pageerror", (e) => log("PAGEERROR:", e.message.slice(0, 200)));

await page.goto(BASE + "/login", { waitUntil: "networkidle", timeout: 120_000 });
await page.waitForTimeout(2000);

const btn = page.locator('button[type="submit"]');
for (let i = 0; i < 10; i++) {
  const disabled = await btn.isDisabled().catch(() => "gone");
  log(`t+${i}s button disabled=${disabled}`);
  if (disabled === false) break;
  await page.waitForTimeout(1000);
}
await page.fill("#email", "admin@nexus-ide.com");
await page.fill("#password", "admin123");
await btn.click();
log("clicked");
await page.waitForTimeout(8000);
log("url now:", page.url());
await page.screenshot({ path: "C:/Users/rodri/AppData/Local/Temp/opencode/shots/dbg-after-click.png" });
const token = await page.evaluate(() => localStorage.getItem("nexus.access_token"));
log("token in localStorage:", token ? token.slice(0, 20) + "..." : "NONE");
await browser.close();
