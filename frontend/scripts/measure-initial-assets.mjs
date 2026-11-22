import { chromium } from '@playwright/test';

const target = new URL(process.argv[2] || 'http://127.0.0.1:4174/');
if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1' || target.username || target.password) {
  throw new Error('Use an isolated loopback HTTP preview URL');
}

const browser = await chromium.launch({ headless: true });
try {
  for (const width of [390, 1366]) {
    const context = await browser.newContext({ viewport: { width, height: 844 }, serviceWorkers: 'block' });
    try {
      const page = await context.newPage();
      await page.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== target.origin || url.pathname.startsWith('/api/')) return route.abort();
        return route.continue();
      });
      await page.goto(target.href, { waitUntil: 'networkidle' });
      await page.evaluate(() => document.fonts.ready);
      const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(entry => ({
        path: new URL(entry.name).pathname,
        transferSize: entry.transferSize,
        encodedBodySize: entry.encodedBodySize,
      })));
      const groups = {};
      for (const item of resources) {
        const type = item.path.match(/\.(js|css|woff2)$/)?.[1] || 'other';
        const group = groups[type] ||= { count: 0, transferSize: 0, encodedBodySize: 0 };
        group.count += 1;
        group.transferSize += item.transferSize;
        group.encodedBodySize += item.encodedBodySize;
      }
      console.log(JSON.stringify({ width, groups }));
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
}
