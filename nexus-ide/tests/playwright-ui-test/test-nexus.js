const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUTPUT_DIR = path.join(__dirname, 'output');
if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR, { recursive: true });

const results = {
  homepage: {},
  missionControl: {},
  chat: {},
  responsive: {},
  links: {},
  consoleErrors: [],
  performance: {},
  issues: [],
  recommendations: []
};

async function runTests() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });

  // Collect console errors globally
  context.on('page', page => {
    page.on('console', msg => {
      const type = msg.type();
      if (type === 'error') {
        results.consoleErrors.push({ page: page.url(), type, text: msg.text() });
      }
    });
    page.on('pageerror', err => {
      results.consoleErrors.push({ page: page.url(), type: 'pageerror', text: err.message });
    });
  });

  const page = await context.newPage();

  // ========== 1. HOMEPAGE ==========
  console.log('Testing homepage...');
  const homeStart = Date.now();
  let homeResponse;
  try {
    homeResponse = await page.goto('http://localhost:3000', { waitUntil: 'networkidle', timeout: 30000 });
  } catch (e) {
    homeResponse = await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 30000 });
  }
  const homeLoadTime = Date.now() - homeStart;
  results.performance.homepageLoad = homeLoadTime;
  results.homepage.status = homeResponse ? homeResponse.status() : 'unknown';
  results.homepage.url = page.url();

  await page.waitForTimeout(3000);

  await page.screenshot({ path: path.join(OUTPUT_DIR, 'homepage.png'), fullPage: false });
  console.log('Homepage screenshot saved');

  const title = await page.title().catch(() => 'unknown');
  results.homepage.title = title;

  const header = await page.locator('header').first();
  results.homepage.headerVisible = await header.isVisible().catch(() => false);

  const sidebar = await page.locator('aside, nav').first();
  results.homepage.sidebarVisible = await sidebar.isVisible().catch(() => false);

  const missionControlLink = await page.locator('text=Mission Control').first();
  results.homepage.missionControlLinkVisible = await missionControlLink.isVisible().catch(() => false);

  // ========== 2. MISSION CONTROL ==========
  console.log('Testing Mission Control...');
  const mcStart = Date.now();
  let mcResponse;
  try {
    mcResponse = await page.goto('http://localhost:3000/mission-control', { waitUntil: 'networkidle', timeout: 30000 });
  } catch (e) {
    mcResponse = await page.goto('http://localhost:3000/mission-control', { waitUntil: 'domcontentloaded', timeout: 30000 });
  }
  const mcLoadTime = Date.now() - mcStart;
  results.performance.missionControlLoad = mcLoadTime;

  await page.waitForTimeout(3000);

  await page.screenshot({ path: path.join(OUTPUT_DIR, 'mission-control.png'), fullPage: false });
  console.log('Mission Control screenshot saved');

  const panelTexts = ['Active Missions', 'Agent Grid', 'Bus Visualizer', 'Quality Gates'];
  for (const text of panelTexts) {
    const el = await page.locator(`text=${text}`).first();
    const visible = await el.isVisible().catch(() => false);
    results.missionControl[text] = visible;
    if (!visible) {
      results.issues.push(`Mission Control panel "${text}" not visible`);
    }
  }

  const mcSidebarLink = await page.locator('text=Mission Control').first();
  results.missionControl.sidebarLinkVisible = await mcSidebarLink.isVisible().catch(() => false);

  // ========== 3. CHAT PANEL ==========
  console.log('Testing Chat panel...');
  const chatBtn = await page.locator('button, [role="button"]').filter({ hasText: /chat/i }).first();
  let chatOpened = false;

  if (await chatBtn.isVisible().catch(() => false)) {
    await chatBtn.click();
    await page.waitForTimeout(1000);
    chatOpened = true;
  } else {
    const buttons = await page.locator('button, [role="button"]').all();
    for (const btn of buttons.slice(0, 8)) {
      try {
        if (await btn.isVisible()) {
          await btn.click();
          await page.waitForTimeout(800);
          const inputs = await page.locator('input, textarea').all();
          for (const inp of inputs) {
            if (await inp.isVisible().catch(() => false)) {
              const ph = await inp.getAttribute('placeholder').catch(() => '');
              if (ph.toLowerCase().includes('chat') || ph.toLowerCase().includes('message') || ph.toLowerCase().includes('mensagem')) {
                chatOpened = true;
                break;
              }
            }
          }
          if (chatOpened) break;
        }
      } catch (e) {}
    }
  }

  results.chat.panelOpened = chatOpened;

  if (chatOpened) {
    const chatInput = await page.locator('input[placeholder*="chat" i], input[placeholder*="message" i], input[placeholder*="mensagem" i], textarea').first();
    if (await chatInput.isVisible().catch(() => false)) {
      await chatInput.fill('Hello NEXUS, this is a test message');
      await chatInput.press('Enter');
      await page.waitForTimeout(4000);

      const pageText = await page.locator('body').innerText();
      results.chat.pageText = pageText.substring(0, 500);
      results.chat.hasResponse = pageText.toLowerCase().includes('hello') && pageText.length > 50;
      await page.screenshot({ path: path.join(OUTPUT_DIR, 'chat-panel.png'), fullPage: false });
    } else {
      results.issues.push('Chat input not found after opening chat');
    }
  } else {
    results.issues.push('Could not open chat panel');
  }

  // ========== 4. RESPONSIVE LAYOUT ==========
  console.log('Testing responsive layout...');
  const sizes = [
    { name: 'mobile', width: 375, height: 667 },
    { name: 'tablet', width: 768, height: 1024 },
    { name: 'desktop', width: 1920, height: 1080 }
  ];

  for (const size of sizes) {
    await page.setViewportSize({ width: size.width, height: size.height });
    try {
      await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 20000 });
    } catch (e) {
      // ignore timeout
    }
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(OUTPUT_DIR, `responsive-${size.name}.png`), fullPage: false });

    const hasHScroll = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    results.responsive[size.name] = { hasHorizontalScroll: hasHScroll };
    if (hasHScroll) {
      results.issues.push(`Horizontal scroll detected at ${size.name} breakpoint`);
    }
  }

  await page.setViewportSize({ width: 1920, height: 1080 });

  // ========== 5. BROKEN LINKS / 404s ==========
  console.log('Testing links for 404s...');
  const linkPage = await context.newPage();
  try {
    await linkPage.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 20000 });
    await linkPage.waitForTimeout(1500);

    const hrefs = await linkPage.evaluate(() => {
      return Array.from(document.querySelectorAll('a[href^="/"]'))
        .map(a => a.getAttribute('href'))
        .filter(h => h && !h.startsWith('//') && !h.startsWith('http'));
    });

    const uniqueHrefs = [...new Set(hrefs)];
    const brokenLinks = [];

    for (const href of uniqueHrefs) {
      try {
        const resp = await linkPage.goto(`http://localhost:3000${href}`, { waitUntil: 'domcontentloaded', timeout: 15000 });
        const status = resp.status();
        if (status === 404) {
          brokenLinks.push({ url: href, status });
          results.issues.push(`Broken link: ${href} returned 404`);
        }
      } catch (e) {
        brokenLinks.push({ url: href, error: e.message });
        results.issues.push(`Broken link: ${href} - ${e.message}`);
      }
    }

    results.links.broken = brokenLinks;
    results.links.totalChecked = uniqueHrefs.length;
    await linkPage.close();
  } catch (e) {
    results.links.error = e.message;
    await linkPage.close();
  }

  // ========== PERFORMANCE METRICS ==========
  console.log('Collecting performance metrics...');
  try {
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1000);
    const perfMetrics = await page.evaluate(() => {
      const nav = performance.getEntriesByType('navigation')[0];
      if (!nav) return null;
      return {
        domContentLoaded: nav.domContentLoadedEventEnd - nav.domContentLoadedEventStart,
        loadComplete: nav.loadEventEnd - nav.loadEventStart,
        firstPaint: performance.getEntriesByType('paint').find(p => p.name === 'first-paint')?.startTime,
        firstContentfulPaint: performance.getEntriesByType('paint').find(p => p.name === 'first-contentful-paint')?.startTime,
        ttfb: nav.responseStart - nav.startTime,
        totalResourceSize: performance.getEntriesByType('resource').reduce((sum, r) => sum + (r.transferSize || 0), 0)
      };
    });
    results.performance.metrics = perfMetrics;
  } catch (e) {
    results.performance.error = e.message;
  }

  // ========== FINAL CHECKS ==========
  if (results.consoleErrors.length > 0) {
    results.issues.push(`${results.consoleErrors.length} console errors detected`);
  }

  if (!results.homepage.missionControlLinkVisible) {
    results.issues.push('Mission Control link not visible in sidebar on homepage');
  }

  // Recommendations
  if (results.consoleErrors.length > 0) {
    results.recommendations.push('Fix console errors before production');
  }
  if (results.performance.homepageLoad > 5000) {
    results.recommendations.push('Homepage load time exceeds 5s - optimize bundle size or enable caching');
  }
  if (results.performance.missionControlLoad > 5000) {
    results.recommendations.push('Mission Control load time exceeds 5s - consider lazy loading panels');
  }
  if (!results.chat.panelOpened) {
    results.recommendations.push('Chat panel could not be located - verify chat button accessibility');
  }
  if (results.links.broken && results.links.broken.length > 0) {
    results.recommendations.push(`Fix ${results.links.broken.length} broken internal links`);
  }
  if (results.missionControl['Active Missions'] === false) {
    results.recommendations.push('Active Missions panel missing - check component rendering');
  }

  await browser.close();

  fs.writeFileSync(path.join(OUTPUT_DIR, 'test-results.json'), JSON.stringify(results, null, 2));
  console.log('Tests complete. Results saved to', OUTPUT_DIR);
}

runTests().catch(err => {
  console.error('Test failed:', err);
  fs.writeFileSync(path.join(OUTPUT_DIR, 'test-results-error.json'), JSON.stringify({ error: err.message, stack: err.stack }, null, 2));
  process.exit(1);
});
