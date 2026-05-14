import { useState, useCallback } from 'react';

/**
 * 마지막 데이터 fetch 성공 시각을 추적한다.
 * { lastRefreshed, markRefreshed }를 반환한다.
 */
export default function useRefreshTimestamp() {
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const markRefreshed = useCallback(() => setLastRefreshed(Date.now()), []);
  return { lastRefreshed, markRefreshed };
}
