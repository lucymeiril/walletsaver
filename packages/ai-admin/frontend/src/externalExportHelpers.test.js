/**
 * externalExportHelpers.test.js
 *
 * 외부 분류 워크플로우 export 헬퍼 단위 테스트.
 * node:test 로 실행: npm test → node --test src/*.test.js
 *
 * 커버리지:
 *  1. 필터 입력 → buildExportPayload 상태 변화
 *  2. export 응답 mock → buildDownloadButtons 다운로드 링크 정확성
 *  3. formatMartFilter → 이력 테이블 마트 필터 표시
 *  4. empty 상태 / availableFormats
 *  5. validateExportForm 유효성 검사
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  MART_OPTIONS,
  FORMAT_OPTIONS,
  buildExportPayload,
  buildDownloadUrl,
  formatMartFilter,
  availableFormats,
  buildDownloadButtons,
  validateExportForm,
} from './externalExportHelpers.js';

// ── 1. buildExportPayload ────────────────────────────────────────────────────

test('buildExportPayload — 전체 마트 선택 시 mart 키 생략', () => {
  const payload = buildExportPayload({
    marts: MART_OPTIONS.map((m) => m.id), // 전체
    capturedSince: '',
    limit: '',
    formats: ['jsonl', 'csv'],
  });
  // 전체 선택 시 mart 키가 없어야 함 (백엔드에서 전체 처리)
  assert.ok(!('mart' in payload), 'mart 키가 없어야 한다 (전체 마트)');
  assert.deepEqual(payload.formats, ['jsonl', 'csv']);
});

test('buildExportPayload — 일부 마트 선택 시 mart 배열 포함', () => {
  const payload = buildExportPayload({
    marts: ['emart', 'costco'],
    capturedSince: '',
    limit: '',
    formats: ['jsonl'],
  });
  assert.deepEqual(payload.mart, ['emart', 'costco']);
});

test('buildExportPayload — capturedSince 입력 시 captured_since 포함', () => {
  const payload = buildExportPayload({
    marts: [],
    capturedSince: '2025-01-01T00:00',
    limit: '',
    formats: ['csv'],
  });
  assert.equal(payload.captured_since, '2025-01-01T00:00');
});

test('buildExportPayload — capturedSince 빈 값이면 생략', () => {
  const payload = buildExportPayload({
    marts: [],
    capturedSince: '',
    limit: '',
    formats: ['csv'],
  });
  assert.ok(!('captured_since' in payload));
});

test('buildExportPayload — limit 숫자 입력 시 포함', () => {
  const payload = buildExportPayload({
    marts: [],
    capturedSince: '',
    limit: '500',
    formats: ['jsonl'],
  });
  assert.equal(payload.limit, 500);
  assert.equal(typeof payload.limit, 'number');
});

test('buildExportPayload — limit 빈 값이면 생략 (무제한)', () => {
  const payload = buildExportPayload({
    marts: [],
    capturedSince: '',
    limit: '',
    formats: ['jsonl'],
  });
  assert.ok(!('limit' in payload));
});

test('buildExportPayload — limit 0이면 생략', () => {
  const payload = buildExportPayload({
    marts: [],
    capturedSince: '',
    limit: '0',
    formats: ['jsonl'],
  });
  assert.ok(!('limit' in payload));
});

test('buildExportPayload — formats 빈 배열이면 전체 형식 포함', () => {
  const payload = buildExportPayload({
    marts: [],
    capturedSince: '',
    limit: '',
    formats: [],
  });
  assert.deepEqual(payload.formats, FORMAT_OPTIONS.map((f) => f.id));
});

// ── 2. buildDownloadUrl — 다운로드 링크 정확성 ─────────────────────────────

test('buildDownloadUrl — jsonl 링크 생성', () => {
  const url = buildDownloadUrl('batch-001', 'jsonl');
  assert.equal(url, '/api/export/unmatched/download?batch_id=batch-001&format=jsonl');
});

test('buildDownloadUrl — csv 링크 생성', () => {
  const url = buildDownloadUrl('batch-002', 'csv');
  assert.equal(url, '/api/export/unmatched/download?batch_id=batch-002&format=csv');
});

test('buildDownloadUrl — zip 링크 생성', () => {
  const url = buildDownloadUrl('batch-003', 'zip');
  assert.equal(url, '/api/export/unmatched/download?batch_id=batch-003&format=zip');
});

test('buildDownloadUrl — batch_id 특수문자 인코딩', () => {
  const url = buildDownloadUrl('batch/abc def', 'jsonl');
  assert.ok(url.includes('batch%2Fabc%20def'), `URL: ${url}`);
});

// ── 3. buildDownloadButtons — export 응답 mock → 결과 카드 다운로드 링크 ──

test('buildDownloadButtons — jsonl+csv 응답 시 JSONL, CSV, ZIP 3개 버튼', () => {
  // mock: POST /api/export/unmatched 응답 예시
  const mockResult = {
    batch_id: 'abc-123',
    hit_count: 10,
    miss_count: 50,
    generated_at: '2025-01-01T00:00:00Z',
    files: { jsonl: '/exports/abc.jsonl', csv: '/exports/abc.csv' },
  };
  const buttons = buildDownloadButtons(mockResult.batch_id, mockResult.files);
  assert.equal(buttons.length, 3);
  assert.equal(buttons[0].format, 'jsonl');
  assert.equal(buttons[1].format, 'csv');
  assert.equal(buttons[2].format, 'zip');
  // URL 정확성 검증
  assert.equal(
    buttons[0].url,
    '/api/export/unmatched/download?batch_id=abc-123&format=jsonl',
  );
  assert.equal(
    buttons[1].url,
    '/api/export/unmatched/download?batch_id=abc-123&format=csv',
  );
  assert.equal(
    buttons[2].url,
    '/api/export/unmatched/download?batch_id=abc-123&format=zip',
  );
});

test('buildDownloadButtons — jsonl만 있으면 ZIP 버튼 없음', () => {
  const buttons = buildDownloadButtons('batch-x', { jsonl: '/exports/x.jsonl' });
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].format, 'jsonl');
});

test('buildDownloadButtons — files null이면 빈 배열', () => {
  const buttons = buildDownloadButtons('batch-x', null);
  assert.equal(buttons.length, 0);
});

test('buildDownloadButtons — 레이블 한국어 확인', () => {
  const buttons = buildDownloadButtons('b', { jsonl: 'x', csv: 'y' });
  assert.equal(buttons[0].label, 'JSONL 다운로드');
  assert.equal(buttons[1].label, 'CSV 다운로드');
  assert.equal(buttons[2].label, 'ZIP(둘 다)');
});

// ── 4. formatMartFilter — 이력 테이블 마트 필터 표시 ────────────────────────

test('formatMartFilter — null/undefined → "전체"', () => {
  assert.equal(formatMartFilter(null), '전체');
  assert.equal(formatMartFilter(undefined), '전체');
});

test('formatMartFilter — 빈 배열 → "전체"', () => {
  assert.equal(formatMartFilter([]), '전체');
});

test('formatMartFilter — 배열 → 콤마 구분 문자열', () => {
  assert.equal(formatMartFilter(['emart', 'costco']), 'emart, costco');
});

test('formatMartFilter — 문자열 그대로 반환', () => {
  assert.equal(formatMartFilter('homeplus'), 'homeplus');
});

// ── 5. availableFormats — empty 상태 / 형식 목록 ────────────────────────────

test('availableFormats — empty 상태 (files null) → 빈 배열', () => {
  // empty 상태: files가 없거나 null일 때
  assert.deepEqual(availableFormats(null), []);
  assert.deepEqual(availableFormats(undefined), []);
  assert.deepEqual(availableFormats({}), []);
});

test('availableFormats — 허용된 형식만 반환 (unknown 키 제외)', () => {
  const result = availableFormats({ jsonl: '/a', csv: '/b', unknown: '/c' });
  assert.deepEqual(result, ['jsonl', 'csv']);
});

test('availableFormats — zip 포함 시 zip 반환', () => {
  const result = availableFormats({ zip: '/a.zip' });
  assert.deepEqual(result, ['zip']);
});

// ── 6. validateExportForm ────────────────────────────────────────────────────

test('validateExportForm — formats 비어있으면 에러 메시지 반환', () => {
  const err = validateExportForm({ formats: [] });
  assert.ok(typeof err === 'string' && err.length > 0, '에러 메시지가 있어야 한다');
  assert.match(err, /형식/);
});

test('validateExportForm — formats 있으면 null 반환 (정상)', () => {
  const err = validateExportForm({ formats: ['jsonl'] });
  assert.equal(err, null);
});

test('validateExportForm — formats jsonl+csv 둘 다 있으면 null', () => {
  const err = validateExportForm({ formats: ['jsonl', 'csv'] });
  assert.equal(err, null);
});
