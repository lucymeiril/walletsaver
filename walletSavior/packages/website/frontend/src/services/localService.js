/**
 * Local 서비스 — SSE 스트리밍 기반 지역 탐색 API
 */

/**
 * SSE 스트리밍으로 카테고리별 결과를 점진적으로 수신한다.
 * @param {Object} params - { locationName, lat, lng, categories, maxItems }
 * @param {Function} onCategory - 카테고리 결과 도착 시 콜백 (categoryData)
 * @param {Function} onDone - 스트리밍 완료 시 콜백
 * @param {Function} onError - 에러 시 콜백
 * @returns {Function} abort 함수
 */
export function streamAreaExplore({ locationName, lat, lng, categories, maxItems = 30 }, onCategory, onDone, onError) {
  const params = new URLSearchParams({ max_items: String(maxItems) });
  if (categories) params.set('categories', categories);
  if (locationName) params.set('location_name', locationName);
  if (lat != null) params.set('lat', String(lat));
  if (lng != null) params.set('lng', String(lng));

  const controller = new AbortController();
  const url = `/api/local/area-explore-stream?${params}`;

  (async () => {
    try {
      const response = await fetch(url, { signal: controller.signal });
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
              return;
            }
            onCategory?.(data);
          } catch { /* skip malformed */ }
        }
      }
      onDone?.({});
    } catch (err) {
      if (err.name !== 'AbortError') {
        onError?.(err);
      }
    }
  })();

  return () => controller.abort();
}
