/**
 * Local 서비스 — SSE 스트리밍 기반 지역 탐색 API
 * 자동 재연결 + 지수 백오프 지원
 */

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 8000;

/**
 * SSE 스트리밍으로 카테고리별 결과를 점진적으로 수신한다.
 * 네트워크 오류 시 지수 백오프로 최대 3회 재연결을 시도한다.
 *
 * @param {Object} params - { locationName, lat, lng, categories, maxItems }
 * @param {Function} onCategory - 카테고리 결과 도착 시 콜백 (categoryData)
 * @param {Function} onDone - 스트리밍 완료 시 콜백
 * @param {Function} onError - 에러 시 콜백 (최종 실패 시)
 * @param {Function} [onRetry] - 재연결 시도 시 콜백 ({ attempt, maxRetries, delayMs })
 * @returns {Function} abort 함수
 */
export function streamAreaExplore(
  { locationName, lat, lng, categories, maxItems = 30 },
  onCategory,
  onDone,
  onError,
  onRetry,
) {
  const params = new URLSearchParams({ max_items: String(maxItems) });
  if (categories) params.set('categories', categories);
  if (locationName) params.set('location_name', locationName);
  if (lat != null) params.set('lat', String(lat));
  if (lng != null) params.set('lng', String(lng));

  const controller = new AbortController();
  const url = `/api/local/area-explore-stream?${params}`;

  // Track which categories we've already received (for dedup on reconnect)
  const receivedCategories = new Set();
  let aborted = false;

  async function readStream() {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const jsonStr = line.slice(6).trim();
        if (!jsonStr) continue;
        try {
          const data = JSON.parse(jsonStr);
          if (data.done) {
            onDone?.(data);
            return true;
          }
          // Dedup: skip categories already received (from prior attempt)
          const catKey = data.name || data.category;
          if (catKey && receivedCategories.has(catKey)) continue;
          if (catKey) receivedCategories.add(catKey);
          onCategory?.(data);
        } catch { /* skip malformed JSON */ }
      }
    }
    onDone?.({});
    return true;
  }

  (async () => {
    let attempt = 0;

    while (attempt <= MAX_RETRIES) {
      try {
        const completed = await readStream();
        if (completed) return;
      } catch (err) {
        if (aborted || err.name === 'AbortError') return;

        attempt++;
        if (attempt > MAX_RETRIES) {
          onError?.(err);
          return;
        }

        const delay = Math.min(BASE_DELAY_MS * 2 ** (attempt - 1), MAX_DELAY_MS);
        onRetry?.({ attempt, maxRetries: MAX_RETRIES, delayMs: delay });

        // Wait before retrying
        await new Promise((resolve) => {
          const timer = setTimeout(resolve, delay);
          controller.signal.addEventListener('abort', () => {
            clearTimeout(timer);
            resolve();
          }, { once: true });
        });

        if (controller.signal.aborted) return;
      }
    }
  })();

  return () => {
    aborted = true;
    controller.abort();
  };
}
