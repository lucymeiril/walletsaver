import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * 디바운스된 값을 반환하는 훅.
 * 입력값이 delay(ms) 동안 변하지 않으면 최종값을 반환한다.
 * 검색 입력 시 불필요한 API 호출을 방지하여 성능을 개선한다.
 */
export function useDebouncedValue(value, delay = 200) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

/**
 * 디바운스된 콜백을 반환하는 훅.
 * 연속 호출 시 마지막 호출만 delay 후에 실행된다.
 */
export function useDebouncedCallback(callback, delay = 200) {
  const timerRef = useRef(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const debounced = useCallback((...args) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => callbackRef.current(...args), delay);
  }, [delay]);

  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  return debounced;
}
