import { test, expect } from '@playwright/test';

test.describe('Dashboard E2E Tests', () => {
  test('should load dashboard page', async ({ page }) => {
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' });

    await expect(page).toHaveTitle(/Dashboard.*NEXUS IDE/);
    await expect(page.getByRole('heading', { name: 'Painel de Operações' })).toBeVisible();
  });

  test('should display system metrics', async ({ page }) => {
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('Latência p95', { exact: true })).toBeVisible();
    await expect(page.getByText('Taxa de sucesso', { exact: true })).toBeVisible();
  });

  test('should display agent network topology', async ({ page }) => {
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('heading', { name: 'Orquestração multi-agente' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Abrir Swarm' })).toBeVisible();
  });

  test('should handle navigation', async ({ page }) => {
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' });

    await Promise.all([
      page.waitForURL(/\/editor$/, { timeout: 20_000 }),
      page.getByRole('link', { name: 'Editor' }).click(),
    ]);
  });
});
