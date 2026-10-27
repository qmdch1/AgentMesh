import { test, expect } from '@playwright/test';
import { scenarios } from '../../src/flows.js';
test('all scenarios finish with a verified result using single steps', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  for (const scenario of scenarios) {
    await page.locator(`[data-scenario="${scenario.id}"]`).click();
    for (let i = 0; i < scenario.steps.length; i++) await page.getByRole('button', { name: '한 단계' }).click();
    await expect(page.locator('#run-badge')).toHaveText('✓ 검증 완료');
    await expect(page.locator('#timeline li')).toHaveCount(scenario.steps.length);
    await expect(page.locator('#timeline li').last()).toContainText('최종 결과 반환');
  }
  expect(errors).toEqual([]);
});
test('packets move, pause, resume, reset and cancel on scenario switching', async ({ page }) => {
  await page.goto('/');
  await page.locator('#speed').selectOption('2');
  await page.locator('#play').click();
  await expect(page.locator('.packet')).toHaveAttribute('visibility', 'visible');
  const firstPosition = await page.locator('.packet').getAttribute('transform');
  await expect.poll(() => page.locator('.packet').getAttribute('transform')).not.toBe(firstPosition);
  await page.locator('#play').click();
  const pausedPosition = await page.locator('.packet').getAttribute('transform');
  await page.waitForTimeout(200);
  expect(await page.locator('.packet').getAttribute('transform')).toBe(pausedPosition);
  await page.locator('#play').click();
  await expect(page.locator('#event-count')).not.toHaveText('0 EVENTS');
  await page.locator('[data-scenario="quick"]').click();
  await expect(page.locator('#event-count')).toHaveText('0 EVENTS');
  await expect(page.locator('.packet')).toHaveAttribute('visibility', 'hidden');
  await page.locator('#play').click();
  await expect(page.locator('#run-badge')).toHaveText('✓ 검증 완료', { timeout: 10000 });
  await page.locator('#play').click();
  await expect(page.locator('#run-badge')).toHaveText('● 이동 중');
  await page.locator('#reset').click();
  await expect(page.locator('#progress-label')).toHaveText('0 / 4 단계');
});
test('mobile layout stays in the viewport and node details work with keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const claude = page.locator('#node-claude');
  await claude.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#node-detail')).toContainText('복잡한 요구사항의 설계');
  await expect(claude).toHaveAttribute('aria-pressed', 'true');
});
test('reduced motion hides moving packets while preserving progress', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.locator('#speed').selectOption('2');
  await page.locator('#play').click();
  await expect(page.locator('#event-count')).not.toHaveText('0 EVENTS');
  await expect(page.locator('.packet')).toHaveAttribute('visibility', 'hidden');
});
