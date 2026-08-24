const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const reqs = [];
  page.on('response', (r) => {
    if (r.url().includes('/api/metrics') || r.url().includes('/api/system')) {
      reqs.push(`${r.status()} ${r.url().replace('http://localhost:3000', '')}`);
    }
  });
  page.on('console', (m) => {
    if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160));
  });
  await page.goto('http://localhost:3000/projects', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(15000);
  console.log('metrics/system responses:');
  reqs.slice(0, 10).forEach((r) => console.log(' ', r));
  if (!reqs.length) console.log('  (nenhuma chamada /api/metrics!)');
  await page.screenshot({ path: 'shots/projects-net.png' });
  await browser.close();
})();
