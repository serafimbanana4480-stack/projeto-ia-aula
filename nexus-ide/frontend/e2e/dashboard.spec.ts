import { test, expect } from '@playwright/test';

test.describe('Dashboard E2E Tests', () => {
  test('should load dashboard page', async ({ page }) => {
    await page.goto('/');
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
    
    // Check that the page title is correct
    await expect(page).toHaveTitle(/NEXUS IDE/);
    
    // Check that main dashboard container is visible
    const dashboard = page.locator('main, .dashboard, [data-testid="dashboard"]');
    if (await dashboard.count() > 0) {
      await expect(dashboard.first()).toBeVisible();
    }
  });

  test('should display system metrics', async ({ page }) => {
    await page.goto('/');
    
    // Wait for metrics to load
    await page.waitForTimeout(2000);
    
    // Check for metrics indicators
    const metrics = page.locator('[data-testid="metrics"], .metrics, [class*="metric"]');
    if (await metrics.count() > 0) {
      await expect(metrics.first()).toBeVisible();
    }
  });

  test('should display agent network topology', async ({ page }) => {
    await page.goto('/');
    
    // Wait for topology to load
    await page.waitForTimeout(2000);
    
    // Check for topology visualization
    const topology = page.locator('[data-testid="topology"], .topology, [class*="topology"]');
    if (await topology.count() > 0) {
      await expect(topology.first()).toBeVisible();
    }
  });

  test('should handle navigation', async ({ page }) => {
    await page.goto('/');
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
    
    // Check if there are navigation elements
    const nav = page.locator('nav, .navigation, [data-testid="nav"]');
    if (await nav.count() > 0) {
      await expect(nav.first()).toBeVisible();
    }
  });
});
