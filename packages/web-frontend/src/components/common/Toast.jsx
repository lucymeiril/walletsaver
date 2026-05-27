import { useEffect, useCallback, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react';
import s from './Toast.module.css';

const ICONS = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

function ToastItem({ toast, onDismiss }) {
  const [exiting, setExiting] = useState(false);
  const Icon = ICONS[toast.type] || Info;

  const handleDismiss = useCallback(() => {
    setExiting(true);
    setTimeout(() => onDismiss(toast.id), 250);
  }, [toast.id, onDismiss]);

  useEffect(() => {
    if (toast.duration === 0) return;
    const timer = setTimeout(handleDismiss, toast.duration || 4000);
    return () => clearTimeout(timer);
  }, [toast.duration, handleDismiss]);

  return (
    <div className={`${s.toast} ${s[toast.type]} ${exiting ? s.exit : ''}`} role="alert">
      <Icon className={s.icon} size={18} />
      <p className={s.message}>{toast.message}</p>
      <button className={s.dismiss} onClick={handleDismiss} aria-label="닫기">
        <X size={14} />
      </button>
    </div>
  );
}

export default function ToastContainer({ toasts = [], onDismiss }) {
  if (toasts.length === 0) return null;

  return createPortal(
    <div className={s.container} aria-live="polite">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>,
    document.body
  );
}
