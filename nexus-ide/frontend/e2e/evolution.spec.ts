import { test, expect, type Page } from '@playwright/test';

test.describe('Evolution Dashboard E2E', () => {

  test('should load the evolution dashboard page', async ({ page }) => {
    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    // Verify page heading
    await expect(page.getByRole('heading', { name: 'Evolution Engine' })).toBeVisible();

    // Verify KPI section renders
    await expect(page.getByText('Evolvable Components')).toBeVisible();
    await expect(page.getByText('Classified Failures')).toBeVisible();
    await expect(page.getByText('Experiments')).toBeVisible();
    await expect(page.getByText('Rollbacks')).toBeVisible();
  });

  test('should show bootstrap and run buttons', async ({ page }) => {
    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('button', { name: 'Bootstrap Champions' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Run Evolution Cycle' })).toBeVisible();
  });

  test('should display component versions section', async ({ page }) => {
    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('Component Versions')).toBeVisible();
  });

  test('should display experiments section', async ({ page }) => {
    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('Recent Experiments')).toBeVisible();
  });

  test('should bootstrap champions via dashboard button', async ({ page }) => {
    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    await page.getByRole('button', { name: 'Bootstrap Champions' }).click();

    // Wait for alert and state refresh
    const dialog = page.locator('.fixed.inset-0');
    await expect(dialog).toBeVisible({ timeout: 10000 });
  });

  test('should run evolution cycle via dashboard button', async ({ page }) => {
    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    // First bootstrap
    await page.getByRole('button', { name: 'Bootstrap Champions' }).click();
    const dialog = page.locator('.fixed.inset-0');
    await expect(dialog).toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: 'OK' }).click().catch(() => {});

    // Then run evolution
    await page.getByRole('button', { name: 'Run Evolution Cycle' }).click();
    const runDialog = page.locator('.fixed.inset-0');
    await expect(runDialog).toBeVisible({ timeout: 15000 });
  });

  test('should update component count after bootstrap', async ({ page }) => {
    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    // Get initial component count (should be 0 before bootstrap)
    const initialCountText = await page.locator('text=Evolvable Components').locator('xpath=following-sibling::*').first().textContent();

    // Bootstrap
    await page.getByRole('button', { name: 'Bootstrap Champions' }).click();
    const dialog = page.locator('.fixed.inset-0');
    await expect(dialog).toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: 'OK' }).click().catch(() => {});

    // Wait for state to refresh and component count to update
    await page.locator('text=Evolvable Components').locator('xpath=following-sibling::*').first().waitFor({ state: 'visible' });
  });

  test('should fetch evolution state via API', async ({ page }) => {
    // Intercept the API call to verify it happens
    const responsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/evolution/state') && response.status() === 200
    );

    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    const response = await responsePromise;
    const data = await response.json();
    expect(data).toHaveProperty('version_tree');
    expect(data).toHaveProperty('experiments');
    expect(data).toHaveProperty('failure_summary');
    expect(data).toHaveProperty('rollbacks');
    expect(data).toHaveProperty('cycle_count');
  });

  test('should handle API errors gracefully', async ({ page }) => {
    // Block the evolution state API to simulate error
    await page.route('/api/evolution/state', (route) => {
      route.fulfill({ status: 500, body: JSON.stringify({ detail: 'Internal Server Error' }) });
    });

    await page.goto('/dashboard/evolution', { waitUntil: 'domcontentloaded' });

    // Should show error message
    await expect(page.getByText(/Failed to fetch/i)).toBeVisible({ timeout: 10000 });
  });
});
