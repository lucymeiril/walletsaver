import { useState, useCallback } from 'react';

export default function useAsyncAction(asyncFn) {
  const [loading, setLoading] = useState(false);

  const execute = useCallback(async (...args) => {
    if (loading) return;
    setLoading(true);
    try {
      return await asyncFn(...args);
    } finally {
      setLoading(false);
    }
  }, [asyncFn, loading]);

  return [execute, loading];
}
