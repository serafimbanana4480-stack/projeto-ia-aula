const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  for (const [path, name, waitMs] of [
    ['/dashboard', 'dash-long', 15000],
    ['/projects', 'projects-long', 12000],
    ['/metrics', 'metrics-long', 12000],
  ]) {
    try {
      await page.goto('http://localhost:3000' + path, { waitUntil: 'domcontentloaded', timeout: 45000 });
      await page.waitForTimeout(waitMs);
      await page.screenshot({ path: `shots/${name}.png` });
      const text = await page.locator('body').innerText();
      console.log(`${path}: chars=${text.length} | ${text.slice(0, 120).replace(/\n/g, ' | ')}`);
    } catch (e) {
      console.log(`${path}: ERROR ${String(e).slice(0, 120)}`);
    }
  }
  await browser.close();
})();
