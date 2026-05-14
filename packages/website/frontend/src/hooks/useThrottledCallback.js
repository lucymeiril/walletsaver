import { useRef, useCallback } from 'react';

export default function useThrottledCallback(callback, delay = 1000) {
  const lastCallRef = useRef(0);
  const pendingRef = useRef(false);

  return useCallback((...args) => {
    const now = Date.now();
    if (now - lastCallRef.current >= delay && !pendingRef.current) {
      lastCallRef.current = now;
      pendingRef.current = true;
      const result = callback(...args);
      if (result instanceof Promise) {
        result.finally(() => { pendingRef.current = false; });
      } else {
        pendingRef.current = false;
      }
      return result;
    }
  }, [callback, delay]);
}
