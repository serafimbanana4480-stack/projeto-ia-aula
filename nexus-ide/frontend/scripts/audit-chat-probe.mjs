/**
 * Full chat round-trip probe.
 *
 *  1. Sends a real message through the real UI.
 *  2. Captures the raw runtime event journal the backend wrote for the run.
 *  3. Screenshots the rendered result.
 */
import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ORIGIN = process.env.NEXUS_ORIGIN ?? "http://127.0.0.1:3000";
const API = process.env.NEXUS_API ?? "http://127.0.0.1:8000";
const REPO = join(process.cwd(), "..");
const OUT = join(REPO, "data", "screenshots", "audit");
const RUN_CANDIDATES = [
  process.env.NEXUS_RUNS_DIR,
  join(REPO, "data", "runs"),
  join(REPO, "..", "data", "runs"),
  join(REPO, "backend", "data", "runs"),
].filter(Boolean);
const RUNS = RUN_CANDIDATES.find((p) => existsSync(p)) ?? RUN_CANDIDATES[1];
const MESSAGE = process.env.NEXUS_PROBE_MESSAGE ?? "Analisa este projeto e descreve a arquitetura real.";
const TAG = process.env.NEXUS_PROBE_TAG ?? "probe";
mkdirSync(OUT, { recursive: true });

const before = new Set(readdirSync(RUNS).filter((f) => f.endsWith(".jsonl")));

const res0 = await fetch(`${API}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: "admin@nexus-ide.com", password: "5748" }),
});
const auth = await res0.json();

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.addInitScript(
  ([a, r, u, proj]) => {
    localStorage.setItem("nexus.access_token", a);
    localStorage.setItem("nexus.refresh_token", r);
    localStorage.setItem("nexus.user", u);
    if (proj) localStorage.setItem("nexus.currentProject", proj);
  },
  [
    auth.access_token,
    auth.refresh_token,
    JSON.stringify(auth.user ?? {}),
    process.env.NEXUS_PROBE_PROJECT ?? null,
  ],
);
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
page.on("console", (m) => {
  if (m.type() === "error") errors.push("console: " + m.text().slice(0, 300));
});

await page.goto(`${ORIGIN}/`, { waitUntil: "domcontentloaded", timeout: 45000 });
await page.waitForTimeout(6000);

// Make sure the composer is usable before typing.
const composer = page.locator("textarea").first();
await composer.waitFor({ state: "visible", timeout: 20000 });
await composer.fill(MESSAGE);
await page.keyboard.press("Enter");

const deadline = Date.now() + 60000;
let last = "";
while (Date.now() < deadline) {
  await page.waitForTimeout(1500);
  const text = await page.evaluate(() => document.body.innerText);
  if (text !== last) last = text;
  if (/Enviar|em espera|Preparar|no chat|parar/i.test(text) === false) break;
}
await page.waitForTimeout(3000);

await page.screenshot({ path: join(OUT, `chat-${TAG}.png`), fullPage: false });
const bodyText = await page.evaluate(() => document.body.innerText);
writeFileSync(join(OUT, `chat-${TAG}.txt`), bodyText);
console.log("=== VISIBLE TEXT ===");
console.log(bodyText.slice(0, 4000));
console.log("\n=== PAGE ERRORS ===");
console.log(errors.slice(0, 10).join("\n") || "(none)");

await browser.close();

// --- read the durable run journal the backend wrote ---
const after = readdirSync(RUNS).filter((f) => f.endsWith(".jsonl"));
const fresh = after.filter((f) => !before.has(f));
console.log("\n=== NEW RUN JOURNALS ===");
for (const f of fresh) {
  const lines = readFileSync(join(RUNS, f), "utf8")
    .split("\n")
    .filter(Boolean)
    .map((l) => {
      try {
        return JSON.parse(l);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
  console.log(`\n--- ${f} (${lines.length} events) ---`);
  for (const e of lines) {
    const p = e.payload ?? {};
    const keys = Object.keys(p).filter((k) => k !== "facts");
    const brief = {};
    for (const k of keys.slice(0, 6)) {
      const v = p[k];
      brief[k] = typeof v === "string" ? v.slice(0, 110) : v;
    }
    console.log(`seq=${String(e.seq).padStart(3)} ${String(e.type).padEnd(20)} ${JSON.stringify(brief).slice(0, 220)}`);
  }
}
