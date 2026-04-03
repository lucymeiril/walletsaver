import { useEffect } from 'react';
import useStore from '../../stores/appStore';

export default function ToastContainer() {
  const { toasts, removeToast } = useStore();

  useEffect(() => {
    if (toasts.length > 0) {
      const timer = setTimeout(() => removeToast(toasts[0].id), 3000);
      return () => clearTimeout(timer);
    }
  }, [toasts, removeToast]);

  return (
    <div style={{ position:'fixed', bottom:20, right:20, zIndex:400, display:'flex', flexDirection:'column', gap:8 }}>
      {toasts.map(t => (
        <div key={t.id} style={{
          background:'var(--surface)', border:'1px solid var(--border2)', borderRadius:10,
          padding:'14px 20px', fontSize:'.88rem', boxShadow:'0 8px 24px rgba(0,0,0,.3)',
          borderLeft: `3px solid ${
            t.type === 'success' ? 'var(--green)' :
            t.type === 'error' ? 'var(--red, #ef4444)' :
            t.type === 'warning' ? 'var(--orange, #f59e0b)' :
            'var(--accent)'
          }`,
          animation: 'slideInRight .3s var(--ease)',
        }}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}
