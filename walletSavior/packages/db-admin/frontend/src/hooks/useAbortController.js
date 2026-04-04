import { useEffect, useRef, useCallback } from 'react';

/**
 * 컴포넌트 언마운트 또는 의존성 변경 시 진행 중인 fetch 요청을 자동 취소하는 훅.
 *
 * Usage:
 *   const getSignal = useAbortController([page, filter]);
 *   useEffect(() => {
 *     fetchProducts(params, { signal: getSignal() });
 *   }, [page, filter]);
 */
export function useAbortController(deps = []) {
  const controllerRef = useRef(null);

  const getSignal = useCallback(() => {
    if (controllerRef.current) {
      controllerRef.current.abort();
    }
    controllerRef.current = new AbortController();
    return controllerRef.current.signal;
  }, []);

  useEffect(() => {
    return () => {
      if (controllerRef.current) {
        controllerRef.current.abort();
      }
    };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  return getSignal;
}
