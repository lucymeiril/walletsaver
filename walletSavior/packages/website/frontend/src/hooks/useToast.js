import { useState, useCallback } from 'react';

let toastId = 0;

export default function useToast() {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback(({ type = 'info', message, duration = 4000 }) => {
    const id = ++toastId;
    setToasts((prev) => [...prev, { id, type, message, duration }]);
    return id;
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const success = useCallback((message, duration) => addToast({ type: 'success', message, duration }), [addToast]);
  const error = useCallback((message, duration) => addToast({ type: 'error', message, duration }), [addToast]);
  const warning = useCallback((message, duration) => addToast({ type: 'warning', message, duration }), [addToast]);
  const info = useCallback((message, duration) => addToast({ type: 'info', message, duration }), [addToast]);

  return { toasts, addToast, dismissToast, success, error, warning, info };
}
