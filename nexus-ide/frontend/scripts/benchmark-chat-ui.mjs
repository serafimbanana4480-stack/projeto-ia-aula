import { chromium } from "@playwright/test";

const baseUrl = process.argv[2] ?? "http://localhost:3110";
const sampleCount = Math.max(1, Number.parseInt(process.argv[3] ?? "5", 10) || 5);
const screenshotPath = process.argv[4];
const browser = await chromium.launch({ headless: true });
const samples = [];

for (let index = 0; index < sampleCount; index += 1) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });

  await context.addInitScript(() => {
    const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 }))
      .replace(/=/g, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
    localStorage.setItem("nexus.access_token", `e30.${payload}.local-perf`);
    localStorage.setItem("nexus.user", JSON.stringify({ id: "local-perf" }));
    window.__nexusLongTasks = [];
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) window.__nexusLongTasks.push(entry.duration);
      }).observe({ type: "longtask", buffered: true });
    } catch {
      // Long task entries are not supported by every Chromium platform.
    }
  });

  const page = await context.newPage();
  await page.route("**/api/**", async (route) => {
    if (new URL(route.request().url()).pathname === "/api/auth/me") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "local-perf" }),
      });
      return;
    }
    // Keep the benchmark read-only and independent of a live backend.
    await route.abort();
  });

  await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.locator("textarea").first().waitFor({ timeout: 20_000 });
  await page.waitForTimeout(600);
  if (screenshotPath && index === 0) {
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }

  const sample = await page.evaluate(() => {
    const navigation = performance.getEntriesByType("navigation")[0];
    const scripts = performance
      .getEntriesByType("resource")
      .filter((entry) => entry.name.includes(".js"));
    return {
      fcpMs: Math.round(performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? -1),
      domInteractiveMs: Math.round(navigation?.domInteractive ?? -1),
      domNodes: document.getElementsByTagName("*").length,
      jsEncodedBytes: scripts.reduce((sum, entry) => sum + (entry.encodedBodySize || 0), 0),
      jsResourceCount: scripts.length,
      longTasks: window.__nexusLongTasks.length,
      longestTaskMs: Math.round(Math.max(0, ...window.__nexusLongTasks)),
    };
  });

  const modeButton = page.getByRole("button", { name: /Escolher modo/ });
  const start = await page.evaluate(() => performance.now());
  await modeButton.click();
  await page.getByRole("listbox", { name: "Modos disponíveis" }).waitFor({ state: "visible" });
  sample.modeMenuOpenMs = Math.round((await page.evaluate(() => performance.now())) - start);
  await page.keyboard.press("Escape");

  samples.push(sample);
  await context.close();
}

const sorted = (key) => samples.map((sample) => sample[key]).sort((a, b) => a - b);
const median = (key) => sorted(key)[Math.floor(samples.length / 2)];

console.log(JSON.stringify({
  browser: browser.version(),
  baseUrl,
  viewport: "1440x1000",
  reducedMotion: true,
  api: "mock authentication; other API requests aborted",
  sampleCount,
  samples,
  median: Object.fromEntries([
    "fcpMs",
    "domInteractiveMs",
    "domNodes",
    "jsEncodedBytes",
    "modeMenuOpenMs",
    "longTasks",
    "longestTaskMs",
  ].map((key) => [key, median(key)])),
}));

await browser.close();
