/**
 * externalExportHelpers.js
 *
 * 외부 분류 워크플로우 - export 패널용 순수 로직 헬퍼.
 * React 컴포넌트와 분리하여 node:test 로 단위 테스트 가능하도록 함.
 *
 * ⚠️ LivePipelinePanel 과는 무관. LivePipelinePanel 은 "라이브 AI 처리"
 *     (현재 보류 중)이고, 이 파일은 "매칭 미히트 raw 데이터를 JSONL/CSV로
 *     내보내는" 외부 분류 워크플로우용임. 혼동하지 말 것.
 */

/** 지원 마트 목록 */
export const MART_OPTIONS = [
  { id: 'emart', label: '이마트' },
  { id: 'homeplus', label: '홈플러스' },
  { id: 'lottemart', label: '롯데마트' },
  { id: 'costco', label: '코스트코' },
];

/** 지원 출력 형식 목록 */
export const FORMAT_OPTIONS = [
  { id: 'jsonl', label: 'JSONL' },
  { id: 'csv', label: 'CSV' },
];

/**
 * 폼 상태 → POST /api/export/unmatched 요청 바디 변환.
 * - marts 빈 배열 or 전체 선택이면 mart 키 생략 (= 전체)
 * - limit 빈 문자열 or 0이면 생략 (= 무제한)
 * - formats 빈 배열이면 전체 형식 포함
 *
 * @param {{ marts: string[], capturedSince: string, limit: string|number, formats: string[] }} formState
 * @returns {object}
 */
export function buildExportPayload({ marts, capturedSince, limit, formats }) {
  const payload = {};

  // 일부 마트만 선택된 경우만 mart 필드 포함
  if (marts && marts.length > 0 && marts.length < MART_OPTIONS.length) {
    payload.mart = marts;
  }

  if (capturedSince && capturedSince.trim()) {
    payload.captured_since = capturedSince.trim();
  }

  const limitNum = parseInt(limit, 10);
  if (!isNaN(limitNum) && limitNum > 0) {
    payload.limit = limitNum;
  }

  // 형식이 지정되지 않으면 전체
  payload.formats = (formats && formats.length > 0)
    ? formats
    : FORMAT_OPTIONS.map((f) => f.id);

  return payload;
}

/**
 * 다운로드 URL 생성.
 * GET /api/export/unmatched/download?batch_id=...&format=jsonl|csv|zip
 *
 * @param {string} batchId
 * @param {'jsonl'|'csv'|'zip'} format
 * @returns {string}
 */
export function buildDownloadUrl(batchId, format) {
  return `/api/export/unmatched/download?batch_id=${encodeURIComponent(batchId)}&format=${encodeURIComponent(format)}`;
}

/**
 * 이력 항목의 마트 필터를 사람이 읽기 쉬운 문자열로 변환.
 * null/undefined → "전체", 배열 → 콤마 구분, 문자열 그대로.
 *
 * @param {string[]|string|null|undefined} mart
 * @returns {string}
 */
export function formatMartFilter(mart) {
  if (!mart || (Array.isArray(mart) && mart.length === 0)) return '전체';
  if (Array.isArray(mart)) return mart.join(', ');
  return String(mart);
}

/**
 * API 응답의 files 객체에서 사용 가능한 형식 목록 반환.
 * files = { jsonl: "...", csv: "..." } 형태.
 *
 * @param {object|null|undefined} files
 * @returns {string[]}  예: ['jsonl', 'csv']
 */
export function availableFormats(files) {
  if (!files || typeof files !== 'object') return [];
  return Object.keys(files).filter((k) => ['jsonl', 'csv', 'zip'].includes(k));
}

/**
 * export 결과 카드에서 다운로드 버튼 정보를 생성.
 * batch_id 와 files 를 받아 { label, url, format } 배열 반환.
 *
 * @param {string} batchId
 * @param {object} files
 * @returns {{ label: string, url: string, format: string }[]}
 */
export function buildDownloadButtons(batchId, files) {
  const formats = availableFormats(files);
  const buttons = [];

  if (formats.includes('jsonl')) {
    buttons.push({
      label: 'JSONL 다운로드',
      url: buildDownloadUrl(batchId, 'jsonl'),
      format: 'jsonl',
    });
  }
  if (formats.includes('csv')) {
    buttons.push({
      label: 'CSV 다운로드',
      url: buildDownloadUrl(batchId, 'csv'),
      format: 'csv',
    });
  }
  // JSONL + CSV 둘 다 있으면 ZIP 버튼도 추가
  if (formats.includes('jsonl') && formats.includes('csv')) {
    buttons.push({
      label: 'ZIP(둘 다)',
      url: buildDownloadUrl(batchId, 'zip'),
      format: 'zip',
    });
  }

  return buttons;
}

/**
 * 폼 유효성 검사. 에러 메시지 문자열 반환, 정상이면 null.
 *
 * @param {{ formats: string[] }} formState
 * @returns {string|null}
 */
export function validateExportForm({ formats }) {
  if (formats && formats.length === 0) {
    return '출력 형식을 하나 이상 선택하세요.';
  }
  return null;
}
