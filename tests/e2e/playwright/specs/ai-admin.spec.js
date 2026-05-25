// @ts-check
const { test, expect } = require('@playwright/test');
const { snap, appendResult } = require('./_helpers');

const AI_ADMIN = 'http://localhost:5176';

test('G. ai-admin MatchMonitorPanel 표시', async ({ page }) => {
  const defects = [];
  await page.goto(AI_ADMIN);
  await page.waitForLoadState('networkidle').catch(() => {});
  await snap(page, 'G1_ai_admin_home', 'ai-admin 홈');
  const monitor = page.locator('#match-monitor');
  if (await monitor.count() === 0) {
    defects.push('MatchMonitorPanel(#match-monitor) 미발견');
  } else {
    await monitor.scrollIntoViewIfNeeded();
    await snap(page, 'G2_match_monitor', 'MatchMonitorPanel');
    const title = await page.getByText(/매칭 누적 모니터/).count();
    if (title === 0) defects.push('매칭 누적 모니터 타이틀 미발견');
  }
  appendResult({ id: 'G_match_monitor', site: 'ai-admin', status: defects.length === 0 ? 'PASS' : 'FAIL', defects });
  expect.soft(defects).toEqual([]);
});

test('H. PendingEscalationPanel sweep 버튼', async ({ page }) => {
  const defects = [];
  await page.goto(AI_ADMIN);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector('#pending-escalation', { timeout: 20_000 }).catch(() => {});
  await page.locator('#pending-escalation').scrollIntoViewIfNeeded().catch(() => {});
  // Wait for usePendingEscalation hook to settle so SweepButton text leaves "처리 중..." state
  await page.locator('#pending-escalation button', { hasText: '새로고침' }).first().waitFor({ timeout: 20_000 }).catch(() => {});
  await page.waitForTimeout(500);
  const sweepBtn = page.locator('#pending-escalation button[title*="Sweep"], #pending-escalation button[title*="Rule A"]').first();
  if (await sweepBtn.count() === 0) {
    defects.push('Sweep 버튼 미발견 — PendingEscalationPanel 에서 일괄 승급 버튼 노출 누락');
    await snap(page, 'H_no_sweep', 'Sweep 미발견');
  } else {
    await snap(page, 'H1_before_sweep', 'Sweep 클릭 전');
    await sweepBtn.click().catch(() => {});
    await page.waitForTimeout(1500);
    await snap(page, 'H2_after_sweep', 'Sweep 클릭 후');
  }
  appendResult({ id: 'H_sweep', site: 'ai-admin', status: defects.length === 0 ? 'PASS' : 'FAIL', defects });
  expect.soft(defects).toEqual([]);
});

test('I. 분류 작업 후 5초 undo 토스트', async ({ page }) => {
  const defects = [];
  await page.goto(AI_ADMIN);
  await page.waitForLoadState('networkidle').catch(() => {});
  const classify = page.getByRole('button', { name: /^(승인|반려|분류|보내기)$/ }).first();
  if (await classify.count() === 0) {
    defects.push('분류/검수 액션 버튼 미발견 — 5초 undo 토스트 검증 불가');
    await snap(page, 'I_no_classify', '분류 버튼 부재');
  } else {
    await classify.click().catch(() => {});
    await page.waitForTimeout(1000);
    await snap(page, 'I1_after_action', '액션 직후');
    const toast = page.getByText(/되돌리|undo|취소|5초/i).first();
    const seen = await toast.count();
    if (seen === 0) defects.push('5초 undo 토스트 미노출 — 분류 액션 후 취소 옵션 부재');
  }
  appendResult({ id: 'I_undo_toast', site: 'ai-admin', status: defects.length === 0 ? 'PASS' : 'FAIL', defects });
  expect.soft(defects).toEqual([]);
});
