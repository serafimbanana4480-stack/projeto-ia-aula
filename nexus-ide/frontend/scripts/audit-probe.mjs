/**
 * NEXUS audit probe — drives the REAL frontend against the REAL backend.
 *
 * Usage:  node scripts/audit-probe.mjs [route ...]
 * Env:    NEXUS_ORIGIN (default http://127.0.0.1:3000)
 *         NEXUS_API    (default http://127.0.0.1:8000)
 *         NEXUS_OUT    (default ../data/screenshots/audit)
 *
 * Writes screenshots + a JSON report of console errors, page errors and
 * failed network requests for every visited route.
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ORIGIN = process.env.NEXUS_ORIGIN ?? "http://127.0.0.1:3000";
const API = process.env.NEXUS_API ?? "http://127.0.0.1:8000";
const OUT = process.env.NEXUS_OUT ?? join(process.cwd(), "..", "data", "screenshots", "audit");
const routes = process.argv.slice(2);

const DEFAULT_ROUTES = [
  ["/", "chat"],
  ["/dashboard", "dashboard"],
  ["/models", "models"],
  ["/mission-control", "mission-control"],
  ["/nexus", "nexus"],
  ["/tools", "tools"],
  ["/settings", "settings"],
  ["/analytics", "analytics"],
  ["/editor", "editor"],
];

mkdirSync(OUT, { recursive: true });

async function login(page) {
  const res = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: process.env.NEXUS_DEV_EMAIL ?? "admin@nexus-ide.com",
      password: process.env.NEXUS_DEV_PASSWORD ?? "5748",
    }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status} ${await res.text()}`);
  const data = await res.json();
  await page.addInitScript(
    ([access, refresh, user]) => {
      localStorage.setItem("nexus.access_token", access);
      localStorage.setItem("nexus.refresh_token", refresh);
      localStorage.setItem("nexus.user", user);
    },
    [data.access_token, data.refresh_token, JSON.stringify(data.user ?? {})],
  );
  return data;
}

const report = [];

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();

const consoleErrors = [];
const pageErrors = [];
const failedRequests = [];

page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text().slice(0, 500));
});
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 500)));
page.on("requestfailed", (r) =>
  failedRequests.push(`${r.method()} ${r.url()} :: ${r.failure()?.errorText}`),
);
page.on("response", (r) => {
  if (r.status() >= 500) failedRequests.push(`HTTP ${r.status()} ${r.url()}`);
  else if (r.status() === 401 || r.status() === 403) {
    failedRequests.push(`HTTP ${r.status()} ${r.url()}`);
  }
});

await login(page);

const list = routes.length
  ? routes.map((r) => [r, r.replace(/[^\w]+/g, "-").replace(/^-|-$/g, "") || "root"])
  : DEFAULT_ROUTES;

for (const [route, name] of list) {
  consoleErrors.length = 0;
  pageErrors.length = 0;
  failedRequests.length = 0;
  const started = Date.now();
  let status = "ok";
  try {
    await page.goto(`${ORIGIN}${route}`, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(3500);
  } catch (e) {
    status = `nav-error: ${String(e).split("\n")[0]}`;
  }
  const shot = join(OUT, `${name}.png`);
  try {
    await page.screenshot({ path: shot, fullPage: false });
  } catch (e) {
    status += ` | screenshot-failed: ${e.message.split("\n")[0]}`;
  }
  const text = await page.evaluate(() => document.body?.innerText?.slice(0, 1200) ?? "");
  const entry = {
    route,
    name,
    status,
    ms: Date.now() - started,
    title: await page.title().catch(() => ""),
    consoleErrors: [...consoleErrors],
    pageErrors: [...pageErrors],
    failedRequests: [...failedRequests],
    textPreview: text,
  };
  report.push(entry);
  console.log(
    `[${entry.status === "ok" ? "OK " : "ERR"}] ${route.padEnd(18)} ${String(entry.ms).padStart(6)}ms  ce=${entry.consoleErrors.length} pe=${entry.pageErrors.length} fr=${entry.failedRequests.length}`,
  );
  for (const e of entry.consoleErrors.slice(0, 4)) console.log(`      console: ${e}`);
  for (const e of entry.pageErrors.slice(0, 4)) console.log(`      pageerr: ${e}`);
  for (const e of entry.failedRequests.slice(0, 4)) console.log(`      reqfail: ${e}`);
}

writeFileSync(join(OUT, "report.json"), JSON.stringify(report, null, 2));
await browser.close();
console.log(`\nreport -> ${join(OUT, "report.json")}`);
