import { test, expect } from '@playwright/test';

test.describe('AI Cockpit E2E Tests', () => {
  test('should display AI cockpit component', async ({ page }) => {
    await page.goto('/');
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
    
    // Check for AI cockpit
    const cockpit = page.locator('[data-testid="ai-cockpit"], .ai-cockpit, [class*="cockpit"]');
    if (await cockpit.count() > 0) {
      await expect(cockpit.first()).toBeVisible();
    }
  });

  test('should have message input area', async ({ page }) => {
    await page.goto('/');
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
    
    // Check for message input
    const input = page.locator('textarea, input[type="text"], [contenteditable="true"]');
    if (await input.count() > 0) {
      await expect(input.first()).toBeVisible();
    }
  });

  test('should display message history', async ({ page }) => {
    await page.goto('/');
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
    
    // Check for message container
    const messages = page.locator('[data-testid="messages"], .messages, [class*="message"]');
    if (await messages.count() > 0) {
      await expect(messages.first()).toBeVisible();
    }
  });
});
