const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUTPUT_DIR = path.join(__dirname, 'output-v2');
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

  results.homepage.title = await page.title().catch(() => 'unknown');
  results.homepage.headerVisible = await page.locator('header').first().isVisible().catch(() => false);
  results.homepage.sidebarVisible = await page.locator('aside, nav').first().isVisible().catch(() => false);
  results.homepage.missionControlLinkVisible = await page.locator('text=Mission Control').first().isVisible().catch(() => false);
  results.homepage.chatLinkVisible = await page.locator('text=Chat').first().isVisible().catch(() => false);

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

  // Check panels by Portuguese/English text
  const panelChecks = [
    { key: 'Active Missions', texts: ['Missões Ativas', 'Active Missions'] },
    { key: 'Agent Grid', texts: ['Agentes', 'Agent Grid'] },
    { key: 'Bus Visualizer', texts: ['Agent Bus', 'Bus Visualizer'] },
    { key: 'Quality Gates', texts: ['Quality Gates'] }
  ];

  for (const check of panelChecks) {
    let visible = false;
    for (const text of check.texts) {
      const el = await page.locator(`text=${text}`).first();
      if (await el.isVisible().catch(() => false)) {
        visible = true;
        break;
      }
    }
    results.missionControl[check.key] = visible;
    if (!visible) {
      results.issues.push(`Mission Control panel "${check.key}" not visible`);
    }
  }

  results.missionControl.sidebarLinkVisible = await page.locator('text=Mission Control').first().isVisible().catch(() => false);

  // ========== 3. CHAT TEST ==========
  console.log('Testing Chat on homepage...');
  await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2000);

  // The chat input is at the bottom of the homepage
  const chatInput = await page.locator('input[placeholder*="Pergunte"], input[placeholder*="chat" i], input[placeholder*="message" i], textarea').first();
  let chatInputVisible = await chatInput.isVisible().catch(() => false);
  results.chat.inputVisible = chatInputVisible;

  if (chatInputVisible) {
    await chatInput.fill('Hello NEXUS, this is a test message from Playwright');
    await chatInput.press('Enter');
    await page.waitForTimeout(5000);

    // Take screenshot after sending message
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'chat-test.png'), fullPage: false });
    console.log('Chat test screenshot saved');

    const pageText = await page.locator('body').innerText();
    results.chat.messageSent = pageText.includes('Hello NEXUS, this is a test message from Playwright');
    // Check if there's any response (non-empty content after sending)
    results.chat.hasResponse = pageText.includes('Hello NEXUS') && pageText.length > 200;
  } else {
    results.issues.push('Chat input not found on homepage');
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
    } catch (e) {}
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

  // ========== FINAL CHECKS & RECOMMENDATIONS ==========
  if (results.consoleErrors.length > 0) {
    results.issues.push(`${results.consoleErrors.length} console errors detected`);
  }

  if (results.consoleErrors.length > 0) {
    results.recommendations.push('Fix console errors before production');
  }
  if (results.performance.homepageLoad > 5000) {
    results.recommendations.push('Homepage load time exceeds 5s - optimize bundle size or enable caching');
  }
  if (results.performance.missionControlLoad > 5000) {
    results.recommendations.push('Mission Control load time exceeds 5s - consider lazy loading panels');
  }
  if (!results.chat.inputVisible) {
    results.recommendations.push('Chat input not accessible - verify main chat component rendering');
  }
  if (results.links.broken && results.links.broken.length > 0) {
    results.recommendations.push(`Fix ${results.links.broken.length} broken internal links`);
  }
  if (results.responsive.mobile && results.responsive.mobile.hasHorizontalScroll) {
    results.recommendations.push('Mobile layout has horizontal scroll - fix overflow issues for responsive design');
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
