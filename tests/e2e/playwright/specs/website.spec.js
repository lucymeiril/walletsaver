// @ts-check
const { test, expect } = require('@playwright/test');
const { snap, appendResult } = require('./_helpers');

test.describe('website (port 5173) — 사용자 핵심 플로우', () => {

  test('A. 홈 → 검색 → 상품 카드 클릭 → 상세 표시', async ({ page }) => {
    const defects = [];
    let pass = true;
    try {
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
      await snap(page, 'A1_home', '홈 진입');

      const search = page.locator('input[type="search"], input[placeholder*="검색"], input[placeholder*="찾"]').first();
      const searchCount = await search.count();
      if (searchCount === 0) {
        defects.push('홈에 검색 입력을 찾지 못함');
      } else {
        await search.fill('우유').catch((e) => defects.push(`검색 입력 실패: ${e.message}`));
        await page.waitForTimeout(800);
        await snap(page, 'A2_home_search_typed', '검색어 입력');

        await search.press('Enter').catch(() => {});
        await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
        await snap(page, 'A3_search_results', '검색 결과');

        const url = page.url();
        if (!/\/search/.test(url) && !/q=/.test(url)) {
          defects.push(`검색 후 URL이 /search 또는 q= 를 포함하지 않음: ${url}`);
        }

        const card = page.locator('[role="button"], button, a, article, li').filter({ hasText: /우유|원|₩|개/i }).first();
        if (await card.count() > 0) {
          await card.click().catch(() => {});
          await page.waitForTimeout(1200);
          await snap(page, 'A4_detail', '상세');
        } else {
          defects.push('검색 결과에서 클릭 가능한 상품 카드를 찾지 못함');
        }
      }
    } catch (e) {
      pass = false;
      defects.push(String(e.message || e));
    }
    appendResult({ id: 'A_search_to_detail', site: 'website', status: pass && defects.length === 0 ? 'PASS' : 'FAIL', defects });
    expect.soft(defects, '결함 없음').toEqual([]);
  });

  test('B. 핫딜러 ON/OFF 모드 토글 (정보량 변화)', async ({ page }) => {
    const defects = [];
    let pass = true;
    try {
      await page.goto('/');
      await page.waitForLoadState('networkidle').catch(() => {});
      const toggle = page.getByRole('button', { name: /핫딜러|핫딜 모드|hotdealer|Hotdealer/i }).first();
      const exists = await toggle.count();
      if (exists === 0) {
        defects.push('핫딜러 ON/OFF 모드 토글 UI 미구현 — 헤더/홈 어디에도 토글 버튼을 찾지 못함');
        pass = false;
        await snap(page, 'B_no_toggle', '토글 부재');
      } else {
        await snap(page, 'B1_before_toggle', '토글 전');
        await toggle.click();
        await page.waitForTimeout(600);
        await snap(page, 'B2_after_toggle', '토글 후');
      }
    } catch (e) { pass = false; defects.push(String(e.message || e)); }
    appendResult({ id: 'B_hotdealer_toggle', site: 'website', status: pass && defects.length === 0 ? 'PASS' : 'FAIL', defects });
    expect.soft(defects).toEqual([]);
  });

  test('C. TrustBadge 3종 (공식/검증/주의) 카드 표시', async ({ page }) => {
    const defects = [];
    await page.goto('/');
    await page.waitForLoadState('networkidle').catch(() => {});
    const badgeSelectors = [/공식/, /검증/, /주의/];
    const missing = [];
    for (const re of badgeSelectors) {
      const c = await page.getByText(re).count();
      if (c === 0) missing.push(re.source);
    }
    if (missing.length) {
      defects.push(`TrustBadge 배지 미발견: ${missing.join(', ')} — 공식/검증/주의 3종 배지 컴포넌트가 구현되지 않음`);
    }
    await snap(page, 'C_trustbadge', 'TrustBadge 검사');
    appendResult({ id: 'C_trustbadge', site: 'website', status: defects.length === 0 ? 'PASS' : 'FAIL', defects });
    expect.soft(defects).toEqual([]);
  });

  test('D. PriceGauge displayPrice = current_low ?? p10 (p50 회귀 차단)', async ({ page }) => {
    const defects = [];
    const fs = require('fs');
    const path = require('path');
    const srcDir = path.resolve(__dirname, '..', '..', '..', '..', 'packages', 'website', 'frontend', 'src');
    function walk(d, files = []) {
      if (!fs.existsSync(d)) return files;
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) walk(p, files);
        else if (/\.(jsx?|tsx?)$/.test(e.name)) files.push(p);
      }
      return files;
    }
    const files = walk(srcDir);
    let gaugeRefs = [];
    let p50Fallback = [];
    let goodPattern = [];
    for (const f of files) {
      const s = fs.readFileSync(f, 'utf8');
      if (/PriceGauge|displayPrice/.test(s)) gaugeRefs.push(f);
      if (/current_low\s*\?\?\s*p50/.test(s)) p50Fallback.push(f);
      if (/current_low\s*\?\?\s*p10/.test(s)) goodPattern.push(f);
    }
    if (gaugeRefs.length === 0) {
      defects.push('PriceGauge / displayPrice 식별자가 소스에 없음 — 컴포넌트 미구현 (회귀 가드만 작동)');
    }
    if (p50Fallback.length > 0) {
      defects.push(`p50 fallback 회귀 검출: ${p50Fallback.join('; ')}`);
    }
    await snap(page, 'D_pricegauge', 'PriceGauge 정적 검사');
    appendResult({ id: 'D_pricegauge_no_p50', site: 'website', status: defects.length === 0 ? 'PASS' : 'FAIL', defects, gaugeRefs, goodPattern });
    expect.soft(defects).toEqual([]);
  });

  test('E. 핫딜 게시판 / 자유 게시판 카테고리 + 글쓰기 진입', async ({ page }) => {
    const defects = [];
    await page.goto('/community');
    await page.waitForLoadState('networkidle').catch(() => {});
    await snap(page, 'E1_community', '커뮤니티 초기');
    const hot = await page.getByText(/핫딜 게시판/).count();
    const free = await page.getByText(/자유 게시판/).count();
    if (hot === 0) defects.push('핫딜 게시판 카테고리 라벨 미발견');
    if (free === 0) defects.push('자유 게시판 카테고리 라벨 미발견');
    const write = page.getByRole('button', { name: /글쓰기|로그인 후 글쓰기/ }).first();
    if (await write.count() === 0) {
      defects.push('글쓰기 진입 버튼 미발견');
    } else {
      await write.click().catch(() => {});
      await page.waitForTimeout(500);
      await snap(page, 'E2_write_clicked', '글쓰기 클릭');
    }
    appendResult({ id: 'E_community_boards', site: 'website', status: defects.length === 0 ? 'PASS' : 'FAIL', defects });
    expect.soft(defects).toEqual([]);
  });

});
