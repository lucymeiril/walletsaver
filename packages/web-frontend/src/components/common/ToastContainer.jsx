import { useEffect, useRef } from 'react';
import useStore from '../../stores/appStore';

const MAX_VISIBLE = 5;

const colorMap = {
  success: 'var(--green)',
  error: 'var(--red, #ef4444)',
  warning: 'var(--orange, #f59e0b)',
  info: 'var(--accent)',
};

export default function ToastContainer() {
  const { toasts, removeToast } = useStore();
  const timersRef = useRef(new Map());

  useEffect(() => {
    const currentIds = new Set(toasts.map(t => t.id));

    for (const [id, timer] of timersRef.current) {
      if (!currentIds.has(id)) {
        clearTimeout(timer);
        timersRef.current.delete(id);
      }
    }

    for (const toast of toasts) {
      if (!timersRef.current.has(toast.id)) {
        const duration = toast.duration || 4000;
        const timer = setTimeout(() => {
          timersRef.current.delete(toast.id);
          removeToast(toast.id);
        }, duration);
        timersRef.current.set(toast.id, timer);
      }
    }
  }, [toasts, removeToast]);

  useEffect(() => {
    return () => {
      for (const timer of timersRef.current.values()) clearTimeout(timer);
      timersRef.current.clear();
    };
  }, []);

  const visible = toasts.slice(-MAX_VISIBLE);

  return (
    <div
      role="region"
      aria-live="polite"
      aria-label="알림"
      style={{
        position: 'fixed', bottom: 20, right: 20, zIndex: 400,
        display: 'flex', flexDirection: 'column', gap: 8,
      }}
    >
      {visible.map(t => (
        <div
          key={t.id}
          role="status"
          style={{
            background: 'var(--surface)', border: '1px solid var(--border2)', borderRadius: 10,
            padding: '14px 20px', fontSize: '.88rem', boxShadow: '0 8px 24px rgba(0,0,0,.3)',
            borderLeft: `3px solid ${colorMap[t.type] || colorMap.info}`,
            animation: 'slideInRight .3s var(--ease)',
            cursor: 'pointer',
          }}
          onClick={() => removeToast(t.id)}
          title="클릭하여 닫기"
        >
          {t.msg}
        </div>
      ))}
    </div>
  );
}
