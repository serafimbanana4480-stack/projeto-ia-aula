import { chromium } from "playwright";
const OUT = "C:/Users/rodri/AppData/Local/Temp/opencode/shots";
const log = (...a) => console.log("[webtest2]", ...a);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));

// login (token may persist per context — fresh context => login again)
await page.goto("http://localhost:3000/login", { waitUntil: "networkidle", timeout: 120_000 });
await page.waitForTimeout(1500);
if (page.url().includes("/login")) {
  await page.fill("#email", "admin@nexus-ide.com");
  await page.fill("#password", "admin123");
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !String(u).includes("/login"), { timeout: 45_000 });
}
log("logged in:", page.url());
await page.waitForSelector("textarea", { timeout: 30_000 });
await page.waitForTimeout(4000);

// send message that triggers a tool
const textarea = page.locator("textarea").first();
await textarea.fill("Lista os ficheiros do diretorio atual e diz quantos ha no total.");
await textarea.press("Enter");
log("sent");

// poll for completion: the stop button (red) disappears + 'a pensar' gone
let toolSeen = false;
let done = false;
for (let i = 0; i < 60; i++) {
  await page.waitForTimeout(2000);
  const timeline = await page.locator('[data-testid="run-timeline-toggle"]').count();
  if (!toolSeen && timeline > 0) {
    toolSeen = true;
    log("run timeline appeared, expanding…");
    try {
      await page.locator('[data-testid="run-timeline-toggle"]').last().click({ timeout: 3000 });
    } catch {}
    await page.waitForTimeout(800);
    // scroll the new message into view
    await page.locator('[data-testid="run-step"]').last().scrollIntoViewIfNeeded().catch(() => {});
    await page.screenshot({ path: `${OUT}/10-timeline-open.png` });
    log("timeline screenshot saved");
  }
  const stopVisible = await page.locator('button:has(svg.lucide-circle-stop), button[title*="Parar"], button[title*="parar"]').count();
  const thinking = await page.locator("text=a pensar").count();
  const live = await page.locator("text=ao vivo").count();
  if (i > 6 && live === 0 && thinking === 0 && stopVisible === 0) { done = true; break; }
}
log("done:", done, "toolSeen:", toolSeen);
await page.waitForTimeout(1500);
// scroll chat to the very bottom
await page.keyboard.press("End").catch(() => {});
await page.evaluate(() => {
  const els = Array.from(document.querySelectorAll("div")).filter((d) => d.scrollHeight > d.clientHeight + 50 && d.querySelector("textarea"));
  els.forEach((e) => (e.scrollTop = e.scrollHeight));
});
await page.waitForTimeout(1200);
await page.screenshot({ path: `${OUT}/11-final-bottom.png` });
log("final bottom screenshot saved");

// hover last assistant message to reveal action buttons (copy/regenerate)
const bubbles = await page.locator("text=NEXUS").all();
log("nexus labels:", bubbles.length);
log("errors:", errors.length, errors.slice(0, 5));
await browser.close();
