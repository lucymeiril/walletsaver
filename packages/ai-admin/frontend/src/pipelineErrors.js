/**
 * rd4-advanced-rewrite: 고급 탭 전용 에러 분류기.
 *
 * 사용자 비판: "잡 등록 실패: [object Object]" / "AI 제안이 부족 — 가동하세요" 등
 * 모호한 메시지로는 다음 행동을 알 수 없다. 백엔드/네트워크/공급자/검증 실패를
 * 구분 가능한 카테고리로 분류해 각 케이스별 "다음 행동" 한 줄을 노출한다.
 *
 * 순수 함수 — DOM/네트워크 의존 없음. node:test 단위 테스트 가능.
 *
 * Kinds (확장 ‑ rd4):
 *   - down        : 백엔드 자체 미응답 (Failed to fetch / TypeError)
 *   - timeout     : 504 또는 "timed out" / "timeout" 문자열
 *   - connection  : 502 또는 ECONNRESET / connection refused
 *   - auth        : 401 / 403
 *   - quota       : 429 / quota / rate limit
 *   - validation  : 422 / pydantic validation error
 *   - provider_500: ai-admin 자체 5xx (timeout/connection 제외한 500/503)
 *   - other       : 그 외 4xx 또는 unknown
 */

const NEXT_BY_KIND = {
  down: {
    label: '백엔드 끊김',
    hint: 'ai-admin 8200 / crawler-admin 8300 프로세스가 살아있는지 확인하세요.',
    next: 'R 키로 재시도',
  },
  timeout: {
    label: '타임아웃',
    hint: '600s 한도를 넘었습니다. batch size를 줄이거나 (max_ai_batch_items 4 권장) 더 빠른 모델로 바꾸세요.',
    next: 'batch size 줄이기',
  },
  connection: {
    label: '연결 실패',
    hint: 'ai-admin → 외부 공급자 연결 실패. 네트워크/프록시/방화벽 확인.',
    next: '공급자 상태 확인',
  },
  auth: {
    label: 'API 인증 실패',
    hint: '공급자(예: Gemma/Gemini) API 키가 누락/만료. ProvidersPanel에서 키 재등록.',
    next: '공급자 키 등록',
  },
  quota: {
    label: '쿼터 초과',
    hint: '공급자 quota / rate limit 초과. 잠시 후 재시도하거나 다른 provider로 fallback.',
    next: '잠시 후 재시도',
  },
  validation: {
    label: '검증 실패',
    hint: '요청 페이로드가 스키마를 통과하지 못함. 상세 detail 확인.',
    next: '요청 페이로드 점검',
  },
  provider_500: {
    label: '백엔드 5xx',
    hint: 'ai-admin 자체 오류. 서버 로그(logs/ai-admin.log) 확인.',
    next: '서버 로그 확인',
  },
  other: {
    label: '기타 오류',
    hint: '분류되지 않은 오류 — 원문 메시지 확인.',
    next: '원문 확인',
  },
};

/**
 * fetch 결과 또는 Error 를 받아 사람이 읽을 수 있는 분류 결과를 돌려준다.
 *
 * @param {Error|string|null|{status?: number, detail?: any}} err
 * @returns {null|{kind: keyof NEXT_BY_KIND, label: string, hint: string, next: string, message: string}}
 */
export function classifyPipelineError(err) {
  if (err == null || err === '') return null;

  let message = '';
  let status = 0;
  if (err && typeof err === 'object') {
    if (typeof err.status === 'number') status = err.status;
    message = humanizeDetail(err.message ?? err.detail ?? err);
  } else {
    message = String(err);
  }
  const m = String(message);
  const lower = m.toLowerCase();

  // 우선 명시적 HTTP status 가 있으면 그 것을 신뢰
  const httpMatch = m.match(/HTTP\s+(\d{3})/);
  if (httpMatch) status = status || Number(httpMatch[1]);

  if (/Failed to fetch|NetworkError|fetch failed|ERR_CONNECTION/i.test(m)) {
    return build('down', m);
  }
  if (status === 504 || /timed?\s*out|timeout|read timeout/i.test(lower)) {
    return build('timeout', m);
  }
  if (status === 502 || /ECONNRESET|ECONNREFUSED|connection (refused|reset|aborted)/i.test(m)) {
    return build('connection', m);
  }
  if (status === 401 || status === 403 || /unauthor|forbidden|invalid api key|api key/i.test(lower)) {
    return build('auth', m);
  }
  if (status === 429 || /quota|rate.?limit|too many requests/i.test(lower)) {
    return build('quota', m);
  }
  if (status === 422 || /validation|pydantic|field required/i.test(lower)) {
    return build('validation', m);
  }
  if (status >= 500 && status < 600) {
    return build('provider_500', m);
  }
  return build('other', m);
}

function build(kind, message) {
  return { kind, message, ...NEXT_BY_KIND[kind] };
}

/**
 * detail 이 dict / 객체일 때 [object Object] 가 나오지 않도록 사람이 읽을 수 있는
 * string 으로 변환한다. detail.message / detail.detail / JSON.stringify 순서.
 *
 * 사용자 비판: "잡 등록 실패: [object Object]" 정확히 이 케이스.
 */
export function humanizeDetail(detail) {
  if (detail == null) return '';
  if (typeof detail === 'string') return detail;
  if (detail instanceof Error) return detail.message || String(detail);
  if (Array.isArray(detail)) {
    // FastAPI 422 validation 응답은 detail=[{loc, msg, type}, …] 형태가 흔하다.
    return detail
      .map((d) => {
        if (!d || typeof d !== 'object') return String(d);
        const loc = Array.isArray(d.loc) ? d.loc.join('.') : d.loc;
        const msg = d.msg || d.message || d.error;
        if (loc && msg) return `${loc}: ${msg}`;
        return msg || JSON.stringify(d);
      })
      .join('; ');
  }
  if (typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message;
    if (typeof detail.detail === 'string') return detail.detail;
    if (typeof detail.error === 'string') return detail.error;
    try {
      return JSON.stringify(detail);
    } catch (_) {
      return '[unserializable error]';
    }
  }
  return String(detail);
}

/**
 * /api/jobs/{id} 폴링 응답을 받아 진행률/ETA 를 계산한다.
 *
 * @param {{
 *   status?: string,
 *   processed_count?: number,
 *   total_count?: number,
 *   attempts?: number,
 *   started_at?: string,
 *   updated_at?: string,
 * }} job
 * @returns {{
 *   percent: number,
 *   processed: number,
 *   total: number,
 *   avgSecPerItem: number|null,
 *   etaSec: number|null,
 *   done: boolean,
 *   failed: boolean,
 * }}
 */
export function computeJobProgress(job) {
  if (!job) {
    return { percent: 0, processed: 0, total: 0, avgSecPerItem: null, etaSec: null, done: false, failed: false };
  }
  const processed = Number(job.processed_count ?? 0);
  const total = Number(job.total_count ?? 0);
  const percent = total > 0 ? Math.min(100, Math.floor((processed / total) * 100)) : 0;
  let avgSecPerItem = null;
  let etaSec = null;
  if (job.started_at && processed > 0) {
    const started = Date.parse(job.started_at);
    const now = job.updated_at ? Date.parse(job.updated_at) : Date.now();
    if (!Number.isNaN(started) && !Number.isNaN(now) && now > started) {
      const elapsedSec = (now - started) / 1000;
      avgSecPerItem = elapsedSec / processed;
      if (total > processed) {
        etaSec = avgSecPerItem * (total - processed);
      }
    }
  }
  const done = job.status === 'completed' || job.status === 'partial';
  const failed = job.status === 'failed' || job.status === 'dead_letter' || job.status === 'cancelled';
  return { percent, processed, total, avgSecPerItem, etaSec, done, failed };
}

export function fmtEta(sec) {
  if (sec == null || !Number.isFinite(sec) || sec <= 0) return '—';
  const mins = Math.floor(sec / 60);
  const secs = Math.floor(sec % 60);
  if (mins >= 60) {
    const h = Math.floor(mins / 60);
    return `~${h}h${mins % 60}m`;
  }
  if (mins > 0) return `~${mins}m${String(secs).padStart(2, '0')}s`;
  return `~${secs}s`;
}
