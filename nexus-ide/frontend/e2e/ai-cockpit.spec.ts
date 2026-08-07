import { test, expect } from '@playwright/test';

test.describe('AI Cockpit E2E Tests', () => {
  test('should display AI cockpit component', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    await expect(page.getByTestId('ai-cockpit')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Chat' })).toBeVisible();
  });

  test('should have message input area', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    await expect(page.getByTestId('ai-cockpit')).toBeVisible();
    await expect(page.getByPlaceholder(/Pergunte qualquer coisa/)).toBeVisible();
  });

  test('should display message history', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    await expect(page.getByTestId('messages')).toBeVisible();
  });

  test('should open, filter and select slash commands from the keyboard', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    const input = page.getByPlaceholder(/Pergunte qualquer coisa/);
    await input.fill('/');
    await expect(page.getByTestId('slash-command-menu')).toBeVisible();
    await expect(page.getByRole('option', { name: /\/proof/ })).toBeVisible();

    await input.fill('/pro');
    await input.press('Enter');
    await expect(input).toHaveValue('/proof ');
    await expect(page.getByTestId('slash-command-menu')).toBeHidden();

    await input.fill('https://example.com');
    await expect(page.getByTestId('slash-command-menu')).toBeHidden();
  });
});
