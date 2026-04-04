import { useState, useCallback } from 'react';

/**
 * 개별 데이터 소스의 fetch 에러 상태 및 재시도를 관리한다.
 * { error, clearError, wrapFetch }를 반환한다.
 */
export default function useNetworkError() {
  const [error, setError] = useState(null);

  const clearError = useCallback(() => setError(null), []);

  const wrapFetch = useCallback(
    async (fetchFn) => {
      try {
        setError(null);
        return await fetchFn();
      } catch (err) {
        setError(err);
        throw err;
      }
    },
    [],
  );

  return { error, clearError, wrapFetch };
}
