// @ts-check
const { test, expect } = require('@playwright/test');
const { snap, appendResult } = require('./_helpers');

test('F. 모바일 뷰포트 — 터치 타깃 44px (홈)', async ({ page, viewport }) => {
  const defects = [];
  await page.goto('http://localhost:5173/');
  await page.waitForLoadState('networkidle').catch(() => {});
  await snap(page, `F_mobile_${viewport.width}x${viewport.height}_home`, `모바일 홈 ${viewport.width}`);

  const small = await page.$$eval('button, a[href], [role="button"]', (els) => {
    const out = [];
    for (const el of els) {
      const r = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none') continue;
      if (r.width === 0 || r.height === 0) continue;
      if (r.width < 44 || r.height < 44) {
        out.push({ tag: el.tagName, text: (el.textContent || '').trim().slice(0, 30), w: Math.round(r.width), h: Math.round(r.height) });
      }
      if (out.length >= 30) break;
    }
    return out;
  });

  const totalInteractive = await page.$$eval('button, a[href], [role="button"]', (els) => els.length);
  const ratio = totalInteractive ? small.length / totalInteractive : 0;
  if (ratio > 0.5) {
    defects.push(`인터랙티브 요소 중 ${small.length}/${totalInteractive} (${(ratio*100).toFixed(0)}%)가 44px 미만 — 모바일 터치 가이드라인 위반`);
  }

  appendResult({
    id: `F_mobile_touch_${viewport.width}`,
    site: 'website',
    viewport,
    status: defects.length === 0 ? 'PASS' : 'FAIL',
    smallTargetsSample: small.slice(0, 15),
    totalInteractive,
    smallCount: small.length,
    defects,
  });
  expect.soft(defects).toEqual([]);
});
