/**
 * rd5-process-missing helpers.
 *
 * 사용자 헌법: "AI 처리 가동 (E)" 버튼이 더는 422 가 나면 안 된다. /api/jobs POST
 * 는 단순 enqueue 일 뿐 워커 가동 보장이 없어 961건 missing 이 그대로 남았다.
 * 대신 신규 동기 엔드포인트 POST /api/ingest/process-missing 으로 라벨링 워커를
 * 한 번에 실행한다. 한 번 호출 = limit (≤30) 만큼만 처리하므로 "딸깍 1회로 끝" 을
 * 위해 `runProcessMissingLoop` 가 missing_remaining 이 0 이 되거나 사용자가
 * abort 할 때까지 반복 호출한다.
 */

import { humanizeDetail } from './pipelineErrors.js';

/**
 * 단일 process-missing 호출.
 *
 * @param {object} args
 * @param {string} args.providerId
 * @param {number} [args.limit=30]
 * @param {boolean} [args.dryRun=false]
 * @param {(input: string, init?: object) => Promise<Response>} [args.fetchImpl]
 * @returns {Promise<{ok:boolean, processed:number, proposals_created:number,
 *    missing_remaining:number, errors:any[], status?:string, raw_batch_id?:string}>}
 */
export async function callProcessMissing({
  providerId,
  limit = 30,
  dryRun = false,
  fetchImpl,
}) {
  const fx = fetchImpl || (typeof fetch === 'function' ? fetch : null);
  if (!fx) throw new Error('fetch impl missing');
  const res = await fx('/api/ingest/process-missing', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider_id: providerId, limit, dry_run: dryRun }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body?.detail ?? body;
    let msg = humanizeDetail(detail);
    if (!msg || msg === '{}' || msg === '[]') msg = `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    err.detail = body?.detail ?? body;
    throw err;
  }
  return body;
}

/**
 * "딸깍 1회" 라이브 루프 — missing 이 다 사라질 때까지 자동 반복 호출하되,
 * `abortSignal()` 이 true 를 돌려주면 즉시 중단한다.
 *
 * @param {object} args
 * @param {string} args.providerId
 * @param {number} [args.limit=30]
 * @param {(progress: {processedTotal:number, proposalsTotal:number,
 *    missingRemaining:number, iterations:number}) => void} [args.onProgress]
 * @param {() => boolean} [args.abortSignal]
 * @param {(input: string, init?: object) => Promise<Response>} [args.fetchImpl]
 * @param {number} [args.maxIterations=200] 무한 루프 방지용 안전 상한.
 * @returns {Promise<{processedTotal:number, proposalsTotal:number,
 *    missingRemaining:number, iterations:number, aborted:boolean}>}
 */
export async function runProcessMissingLoop({
  providerId,
  limit = 30,
  onProgress,
  abortSignal,
  fetchImpl,
  maxIterations = 200,
}) {
  let processedTotal = 0;
  let proposalsTotal = 0;
  let missingRemaining = 0;
  let iterations = 0;
  let aborted = false;
  for (let i = 0; i < maxIterations; i += 1) {
    if (abortSignal && abortSignal()) {
      aborted = true;
      break;
    }
    iterations += 1;
    // eslint-disable-next-line no-await-in-loop
    const body = await callProcessMissing({ providerId, limit, fetchImpl });
    processedTotal += Number(body.processed || 0);
    proposalsTotal += Number(body.proposals_created || 0);
    missingRemaining = Number(body.missing_remaining || 0);
    if (onProgress) {
      onProgress({ processedTotal, proposalsTotal, missingRemaining, iterations });
    }
    if (missingRemaining === 0 || (body.processed || 0) === 0) {
      break;
    }
  }
  return { processedTotal, proposalsTotal, missingRemaining, iterations, aborted };
}

/**
 * 진행 라벨 포맷터.
 *
 * @param {{processedTotal:number, missingRemaining:number, initialMissing:number}} p
 */
export function formatProcessMissingLabel(p) {
  if (!p) return '';
  const total = (p.initialMissing || 0);
  const done = p.processedTotal || 0;
  const remain = p.missingRemaining || 0;
  if (total > 0) return `처리 중… (${done}/${total} · 남음 ${remain})`;
  return `처리 중… (${done})`;
}
