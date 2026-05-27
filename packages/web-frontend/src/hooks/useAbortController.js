import { useRef, useEffect, useCallback } from 'react';

/**
 * Returns a function that creates a new AbortController, automatically
 * aborting the previous one. Cleans up on unmount.
 *
 * Usage:
 *   const getSignal = useAbortController();
 *   const signal = getSignal();  // aborts previous, returns new signal
 */
export default function useAbortController() {
  const controllerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (controllerRef.current) controllerRef.current.abort();
    };
  }, []);

  const getSignal = useCallback(() => {
    if (controllerRef.current) controllerRef.current.abort();
    controllerRef.current = new AbortController();
    return controllerRef.current.signal;
  }, []);

  return getSignal;
}
