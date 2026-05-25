// @ts-check
const { test, expect } = require('@playwright/test');
const { snap, appendResult } = require('./_helpers');

const ADMINS = [
  { id: 'db-admin', url: 'http://localhost:5175' },
  { id: 'crawler-admin', url: 'http://localhost:5174' },
];

for (const a of ADMINS) {
  test(`Admin smoke — ${a.id} 로드`, async ({ page }) => {
    const defects = [];
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e.message || e)));
    try {
      const res = await page.goto(a.url, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle').catch(() => {});
      if (!res || !res.ok()) defects.push(`HTTP ${res ? res.status() : '없음'}`);
      await snap(page, `admin_${a.id}_home`, `${a.id} 홈`);
      const bodyText = await page.locator('body').innerText().catch(() => '');
      if (!bodyText || bodyText.length < 20) defects.push('본문 비어 있음');
      if (errors.length) defects.push(`JS error: ${errors.slice(0, 2).join(' | ')}`);
    } catch (e) {
      defects.push(String(e.message || e));
    }
    appendResult({ id: `admin_smoke_${a.id}`, site: a.id, status: defects.length === 0 ? 'PASS' : 'FAIL', defects, jsErrors: errors });
    expect.soft(defects).toEqual([]);
  });
}
