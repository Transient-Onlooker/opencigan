import { chromium } from '@playwright/test';

const browser = await chromium.launch();
try {
  for (const viewport of [{ width: 390, height: 844 }, { width: 1280, height: 800 }]) {
    const page = await browser.newPage({ viewport, serviceWorkers: 'block' });
    try {
      const response = await page.goto('https://opencigan.mcv.kr/', { waitUntil: 'domcontentloaded', timeout: 30000 });
      if (response.status() !== 200) throw new Error('Public HTML did not return 200');
      const search = page.getByRole('searchbox', { name: '학교 찾기' });
      await search.waitFor({ state: 'visible', timeout: 15000 });
      const schoolsResponse = page.waitForResponse((result) =>
        result.url().includes('/api/v1/schools?') && result.status() === 200, { timeout: 30000 });
      await search.fill('대전');
      const schools = (await (await schoolsResponse).json()).schools;
      if (!schools.length) throw new Error('Public school search returned no results');
      const timetableResponse = page.waitForResponse((result) =>
        result.url().includes('/api/v1/timetable?') && result.status() === 200, { timeout: 30000 });
      await page.locator('.school-option').first().click();
      const timetable = await (await timetableResponse).json();
      if (!Array.isArray(timetable.records)) throw new Error('Timetable response is invalid');
      await page.locator('#timetable-panel').waitFor({ state: 'visible', timeout: 15000 });
      console.log(`Public browser flow passed at ${viewport.width}px`);
    } finally {
      await page.close();
    }
  }
} finally {
  await browser.close();
}
