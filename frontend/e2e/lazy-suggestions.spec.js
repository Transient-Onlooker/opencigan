import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test('retry protects unsaved lesson-time drafts', async ({ page }) => {
  test.skip(process.env.VITE_SUGGESTIONS_ENABLED === '0', 'Explicitly disabled build does not load suggestions');
  await page.addInitScript(() => localStorage.setItem('opensigan-school', JSON.stringify({ id: '1:학교', name: '학교', region: '서울' })));
  await page.route('**/assets/Suggestions-*.js', route => route.abort('failed'));
  await page.route('**/api/v1/**', route => route.fulfill({ json: { schools: [], records: [], meals: [], suggestions: [] } }));
  await page.goto('/');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await expect(page.getByText('제안 기능을 불러오지 못했어요.')).toBeVisible();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await page.getByText('상세 시간 설정하기', { exact: true }).click();
  await page.getByLabel('1교시 시작', { exact: true }).fill('08:30');
  await page.getByRole('button', { name: '새로고침 후 다시 시도' }).click();
  await expect(page.getByLabel('1교시 시작', { exact: true })).toHaveValue('08:30');
  await expect(page.getByText('작성 중인 교시 시각을 저장하거나 초기화한 뒤 다시 시도해 주세요.')).toBeVisible();
});

test('suggestions recover after a failed chunk fetch', async ({ page }) => {
  test.skip(process.env.VITE_SUGGESTIONS_ENABLED === '0', 'Explicitly disabled build does not load suggestions');
  let attempts = 0;
  await page.route('**/assets/Suggestions-*.js', route => {
    attempts++;
    return attempts === 1 ? route.abort('failed') : route.continue();
  });
  await page.route('**/api/v1/suggestions**', route => route.fulfill({ json: { suggestions: [], nextCursor: null } }));
  await page.goto('/');
  expect(attempts).toBe(0);
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await expect.poll(() => attempts).toBe(1);
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await expect(page.getByText('만들어주세요', { exact: true })).toBeVisible({ timeout: 5000 });
});

test('reentering settings while a chunk request fails retries after it settles', async ({ page }) => {
  test.skip(process.env.VITE_SUGGESTIONS_ENABLED === '0', 'Explicitly disabled build does not load suggestions');
  let attempts = 0;
  let releaseFirst;
  const firstRequest = new Promise(resolve => { releaseFirst = resolve; });
  await page.route('**/assets/Suggestions-*.js', async route => {
    attempts++;
    if (attempts === 1) { await firstRequest; return route.abort('failed'); }
    return route.continue();
  });
  await page.route('**/api/v1/suggestions**', route => route.fulfill({ json: { suggestions: [], nextCursor: null } }));
  await page.goto('/');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await expect.poll(() => attempts).toBe(1);
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  releaseFirst();
  await expect(page.getByText('만들어주세요', { exact: true })).toBeVisible({ timeout: 5000 });
  expect(attempts).toBe(2);
});
