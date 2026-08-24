const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push('[console] ' + msg.text().slice(0, 200));
  });
  page.on('pageerror', (err) => errors.push('[pageerror] ' + String(err).slice(0, 200)));

  const shot = (name) => page.screenshot({ path: `shots/${name}.png`, fullPage: false });

  // 1. Home (redirect to /login if unauthenticated)
  await page.goto('http://localhost:3000/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(5000);
  await shot('01-initial');
  console.log('URL after goto:', page.url());

  // Login if redirected
  if (page.url().includes('/login')) {
    await page.fill('input[type="email"], input[name="email"]', 'admin@nexus-ide.com').catch(() => {});
    if (!(await page.locator('input[type="email"]').count())) {
      const inputs = await page.locator('input').all();
      console.log('login inputs:', inputs.length);
    }
    await page.fill('input[type="password"]', 'admin123').catch(() => {});
    await shot('02-login-filled');
    await Promise.all([
      page.waitForURL(/(?!.*login).*$/, { timeout: 30000 }).catch(() => {}),
      page.click('button[type="submit"]').catch(() => {}),
    ]);
    await page.waitForTimeout(4000);
    await shot('03-after-login');
    console.log('URL after login:', page.url());
  }

  // 2. Chat empty state
  await page.goto('http://localhost:3000/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(6000);
  await shot('04-chat-empty');

  // 3. Mode dropdown
  const modeBtn = page.locator('button[title="Escolher modo"]');
  if (await modeBtn.count()) {
    await modeBtn.click();
    await page.waitForTimeout(600);
    await shot('05-mode-dropdown-open');
    const options = await page.locator('[data-testid="mode-dropdown-menu"] button').count();
    console.log('mode options visible:', options);
    await page.keyboard.press('Escape');
  } else {
    console.log('MODE BUTTON NOT FOUND');
  }

  // 4. Send a real message through the UI
  const textarea = page.locator('textarea');
  if (await textarea.count()) {
    await textarea.first().click();
    await textarea.first().fill('Diz olá e lista 2 pastas do projeto usando ferramentas.');
    await shot('06-input-filled');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(12000); // let it stream
    await shot('07-streaming-mid');
    await page.waitForTimeout(25000);
    await shot('08-after-response');
    const msgs = await page.locator('[data-testid="messages"] > div > div').count();
    console.log('message blocks rendered:', msgs);
  } else {
    console.log('TEXTAREA NOT FOUND');
  }

  // 5. Other pages render
  for (const [path, name] of [['/dashboard', '09-dashboard'], ['/projects', '10-projects'], ['/settings', '11-settings']]) {
    try {
      await page.goto('http://localhost:3000' + path, { waitUntil: 'domcontentloaded', timeout: 45000 });
      await page.waitForTimeout(3500);
      await shot(name);
      console.log(`page ${path}: ok`);
    } catch (e) {
      console.log(`page ${path}: ERROR ${String(e).slice(0, 100)}`);
    }
  }

  console.log('--- JS ERRORS ---');
  errors.slice(0, 12).forEach((e) => console.log(e));
  if (!errors.length) console.log('(none)');
  await browser.close();
})();
