import { chromium, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

// This creates a user and conversations. Point it only at disposable, local
// services; never run against a real user database or an actual model provider.
if (process.env.NEXUS_BOTS_DISPOSABLE !== '1') {
  throw new Error('Set NEXUS_BOTS_DISPOSABLE=1 only for a disposable isolated database.');
}
function localOrigin(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.pathname !== '/') {
    throw new Error(`${name} must be a loopback HTTP origin`);
  }
  return url.origin;
}
const frontend = localOrigin('NEXUS_BOTS_TEST_ORIGIN');
const api = localOrigin('NEXUS_BOTS_TEST_API');
const stub = localOrigin('NEXUS_BOTS_STUB_ORIGIN');
const modelsResponse = await fetch(`${stub}/v1/models`);
const models = (await modelsResponse.json()).data ?? [];
if (!modelsResponse.ok || !models.some((model) => model.id === 'nexus-stub-coder' && ['test-double', 'nexus-audit-stub'].includes(model.owned_by))) {
  throw new Error('Expected the explicitly identified local NEXUS stub model.');
}
const shots = path.resolve(process.env.NEXUS_BOTS_ARTIFACT_DIR || path.join(os.tmpdir(), `nexus-bots-proof-${Date.now()}`));
await mkdir(shots, { recursive: false });
const testEmail = `bots-proof-${Date.now()}@example.com`;
const registration = await fetch(`${api}/api/auth/register`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: testEmail, password: 'BotsProof-2026-Only', full_name: 'Teste Bots' }),
});
if (!registration.ok) throw new Error(`Disposable registration failed: ${registration.status}`);
const login = await registration.json();
const catalogResponse = await fetch(`${api}/api/providers/catalog`, {
  headers: { Authorization: `Bearer ${login.access_token}` },
});
if (!catalogResponse.ok) throw new Error('Could not verify the backend provider configuration.');
const catalog = await catalogResponse.json();
const configuredUrl = new URL(catalog.providers.find((provider) => provider.id === 'lmstudio')?.base_url || 'http://127.0.0.1:1');
if (configuredUrl.origin !== stub || configuredUrl.pathname.replace(/\/+$/, '') !== '/v1') {
  throw new Error('The backend LM Studio endpoint does not match the isolated stub.');
}
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
try {
  await page.goto(`${frontend}/login`, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.getByLabel('Email').fill(testEmail, { timeout: 90000 });
  await page.getByLabel('Password').fill('BotsProof-2026-Only');
  await page.getByRole('button', { name: 'Iniciar sessão' }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
  await page.goto(`${frontend}/bots`, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await expect(page.getByRole('heading', { name: 'Bots', exact: true })).toBeVisible({ timeout: 60000 });
  await expect(page.getByText('Ainda não tens bots. Cria o primeiro para começar.')).toBeVisible();
  await page.screenshot({ path: path.join(shots, 'empty-desktop.png') });
  await page.getByRole('button', { name: 'Criar bot' }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Ponto de partida').selectOption({ label: 'UI/UX' });
  await dialog.getByLabel('Nome', { exact: true }).fill('Pixel');
  await dialog.getByLabel('Provedor').selectOption('lmstudio');
  await dialog.getByRole('button', { name: 'Consultar modelos do provedor' }).click();
  await expect(dialog.getByText(/modelo\(s\) encontrados/)).toBeVisible({ timeout: 30000 });
  await dialog.getByLabel('Modelo').fill('nexus-stub-coder');
  await page.screenshot({ path: path.join(shots, 'editor-desktop.png') });
  await dialog.getByRole('button', { name: 'Guardar bot' }).click();
  await expect(page.getByRole('heading', { name: 'Pixel', exact: true })).toBeVisible({ timeout: 30000 });
  await page.getByRole('textbox', { name: 'Mensagem' }).fill('Olá Pixel, apresenta-te.');
  await page.getByRole('button', { name: 'Enviar mensagem' }).click();
  await expect(page.getByText('Olá Pixel, apresenta-te.')).toBeVisible();
  await expect(page.getByLabel('Conversa', { exact: true }).getByText('Olá! Esta é uma resposta simulada para validar o streaming dos Bots.')).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole('button', { name: 'Enviar mensagem' })).toBeVisible({ timeout: 30000 });
  await page.getByRole('button', { name: 'Informações do bot' }).click();
  await expect(page.getByText('Apenas conversa · sem ferramentas')).toBeVisible();
  await page.screenshot({ path: path.join(shots, 'conversation-desktop.png') });
  await page.getByRole('button', { name: 'Arquivar conversa' }).click();
  await expect(page.getByRole('tab', { name: 'Arquivados' })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('button', { name: 'Retirar do arquivo' }).click();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByLabel('Conversa', { exact: true }).getByText('Olá! Esta é uma resposta simulada para validar o streaming dos Bots.')).toBeVisible({ timeout: 60000 });
  await page.getByLabel('Pesquisar conversas').fill('Pixel');
  await expect(page.getByRole('button', { name: /Pixel/ }).first()).toBeVisible();
  await page.getByLabel('Pesquisar conversas').fill('');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Bots', exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole('button', { name: /Pixel/ }).first()).toBeVisible();
  await page.screenshot({ path: path.join(shots, 'list-mobile.png') });
  await page.getByRole('button', { name: /Pixel/ }).first().click();
  await expect(page.getByRole('button', { name: 'Voltar às conversas' })).toBeVisible();
  await expect(page.getByLabel('Conversa', { exact: true }).getByText('Olá! Esta é uma resposta simulada para validar o streaming dos Bots.')).toBeVisible();
  await page.screenshot({ path: path.join(shots, 'conversation-mobile.png') });
  const metrics = await page.evaluate(() => ({ innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth, height: window.innerHeight }));
  if (metrics.scrollWidth > metrics.innerWidth) throw new Error(`Mobile horizontal overflow: ${JSON.stringify(metrics)}`);
  const botSession = await page.evaluate(async (apiOrigin) => {
    const token = localStorage.getItem('nexus.access_token');
    const response = await fetch(`${apiOrigin}/api/bots`, { headers: { Authorization: `Bearer ${token}` } });
    return (await response.json()).bots[0].session_id;
  }, api);
  await page.getByRole('textbox', { name: 'Mensagem' }).fill('Teste de cancelamento.');
  await page.getByRole('button', { name: 'Enviar mensagem' }).click();
  await expect(page.getByRole('button', { name: 'Pedir paragem' })).toBeVisible();
  const cancellationStatus = () => page.evaluate(async ({ sessionId, apiOrigin }) => {
    const token = localStorage.getItem('nexus.access_token');
    const response = await fetch(`${apiOrigin}/api/sessions/${sessionId}/runs`, { headers: { Authorization: `Bearer ${token}` } });
    const rows = (await response.json()).runs ?? [];
    return rows.find((row) => row.prompt === 'Teste de cancelamento.')?.status ?? 'pending';
  }, { sessionId: botSession, apiOrigin: api });
  await expect.poll(cancellationStatus, { timeout: 15000 }).toBe('running');
  const cancelStarted = Date.now();
  await page.getByRole('button', { name: 'Pedir paragem' }).click();
  await expect.poll(cancellationStatus, { timeout: 15000 }).toBe('cancelled');
  const cancelMs = Date.now() - cancelStarted;
  // Wait past the stub's normal completion time. A detached pump must not
  // finish later and overwrite the cancelled outcome with "completed".
  await page.waitForTimeout(6500);
  expect(await cancellationStatus()).toBe('cancelled');
  if (errors.length) throw new Error(`Browser errors: ${errors.join(' | ')}`);
  console.log(JSON.stringify({ outcome: 'PASS', screenshots: shots, metrics, cancellation: 'cancelled', cancelMs, errorCount: errors.length }));
} finally { await browser.close(); }
