import { useEffect, useRef, useCallback } from 'react';

export default function useInfiniteScroll(callback, options = {}) {
  const { threshold = 0.1, rootMargin = '100px', enabled = true } = options;
  const observerRef = useRef(null);
  const targetRef = useRef(null);

  const setTarget = useCallback((node) => {
    targetRef.current = node;
  }, []);

  useEffect(() => {
    if (!enabled || !targetRef.current) return;

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          callback();
        }
      },
      { threshold, rootMargin }
    );

    observerRef.current.observe(targetRef.current);

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [callback, threshold, rootMargin, enabled]);

  return setTarget;
}
