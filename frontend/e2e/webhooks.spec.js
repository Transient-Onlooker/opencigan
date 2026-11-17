import { expect, test } from '@playwright/test';

test('direct webhook entry returns to settings on mobile and desktop', async ({ page }) => {
  for (const width of [320, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('/webhooks.html');
    const link = page.getByRole('link', { name: '설정으로 돌아가기' });
    await expect(link).toHaveAttribute('href', './?view=settings');
    expect((await link.boundingBox()).height).toBeGreaterThanOrEqual(44);
    await link.focus();
    await expect(link).toHaveCSS('outline-style', 'solid');
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\?view=settings$/);
    await expect(page.locator('#settings-panel')).toBeVisible();
    await page.reload();
    await expect(page.locator('#settings-panel')).toBeVisible();
  }
});

test('webhook page shares the app brand and supports light, dark and system themes', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/webhooks.html');
  for (const [preference, expected] of [['light', 'light'], ['dark', 'dark'], ['system', 'dark']]) {
    await page.evaluate((value) => localStorage.setItem('opensigan-theme', value), preference);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', expected);
    const brand = page.getByRole('link', { name: 'Opencigan', exact: true });
    await expect(brand.locator('svg')).toBeVisible();
    await expect(brand).toHaveAttribute('href', './');
    await page.keyboard.press('Tab');
    await brand.focus();
    await expect(brand).toHaveCSS('outline-style', 'solid');
    for (const width of [320, 390, 800, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      expect((await page.getByLabel('Webhook 주소').boundingBox()).height).toBeGreaterThanOrEqual(44);
    }
  }
});

test('subscription management uses bearer token and keeps secrets out of storage', async ({ page }) => {
  const id = 'a'.repeat(24), token = 'b'.repeat(43), calls = [];
  await page.route('**/api/v1/webhooks**', async (route) => {
    const request = route.request(), url = new URL(request.url());
    calls.push({ path: url.pathname, method: request.method(), headers: request.headers(), body: request.postDataJSON() });
    if (url.pathname === '/api/v1/webhooks') return route.fulfill({ json: { id, token, provider: 'discord' } });
    if (url.pathname.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [{ event_id: 'test_1', state: 'delivered', attempts: 1, last_status: 204 }] } });
    if (url.pathname.endsWith('/test')) return route.fulfill({ json: { eventId: 'test_1' } });
    if (request.method() === 'PUT') return route.fulfill({ json: { updated: true } });
    if (request.method() === 'DELETE') return route.fulfill({ json: { deleted: true } });
    return route.fulfill({ json: { school: '2:예시학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
  });
  await page.goto('/webhooks.html');
  await page.getByLabel('학교 ID').fill('2:예시학교');
  await page.getByLabel('학년', { exact: true }).fill('2');
  await page.getByLabel('반', { exact: true }).fill('3');
  await page.getByLabel('Webhook 주소').fill('https://discord.com/api/webhooks/123/secret');
  await page.getByRole('button', { name: '구독 만들기' }).click();
  await expect(page.getByLabel('관리 토큰')).toHaveValue(token);
  await expect(page.getByLabel('Webhook 주소')).toHaveValue('');
  await expect(page.getByRole('status')).toContainText('안전한 곳');
  await page.getByRole('button', { name: '구독 불러오기' }).click();
  await expect(page.getByText('2:예시학교 · 2학년 3반')).toBeVisible();
  await page.getByLabel('과목 포함').fill('수학');
  await page.getByLabel('방해 금지 시작').fill('22:00');
  await page.getByLabel('방해 금지 종료').fill('07:00');
  await page.getByRole('button', { name: '조건 저장' }).click();
  await expect(page.getByRole('status')).toContainText('저장');
  expect(calls.find((call) => call.method === 'PUT').body.filters).toEqual({ subject: '수학', quietHours: { start: '22:00', end: '07:00' } });
  await page.getByRole('button', { name: '테스트 알림' }).click();
  await expect(page.getByRole('status')).toContainText('대기열');
  expect(calls.filter((call) => call.path !== '/api/v1/webhooks').every((call) => call.headers.authorization === `Bearer ${token}`)).toBeTruthy();
  expect(await page.evaluate(() => JSON.stringify({ local: localStorage, session: sessionStorage, url: location.href }))).not.toContain(token);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '구독 삭제' }).click();
  await expect(page.getByLabel('관리 토큰')).toHaveValue('');
  await expect(page.getByRole('status')).toContainText('삭제');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize().width);
});
