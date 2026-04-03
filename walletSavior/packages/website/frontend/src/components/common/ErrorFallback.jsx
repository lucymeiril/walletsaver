import { AlertTriangle, WifiOff, RefreshCw } from 'lucide-react';
import Button from './Button';
import s from './ErrorFallback.module.css';

const ICON_MAP = {
  network: WifiOff,
  timeout: RefreshCw,
  default: AlertTriangle,
};

export default function ErrorFallback({
  error,
  message,
  onRetry,
  className = '',
}) {
  const errorCode = error?.code || 'default';
  const Icon = ICON_MAP[errorCode] || ICON_MAP.default;
  const displayMessage = message || error?.message || '오류가 발생했습니다.';
  const showRetry = onRetry && (error?.retryable !== false);

  return (
    <div className={`${s.wrapper} ${className}`}>
      <Icon className={s.icon} size={44} />
      <p className={s.message}>{displayMessage}</p>
      {showRetry && (
        <Button variant="outline" onClick={onRetry}>
          <RefreshCw size={14} />
          <span>다시 시도</span>
        </Button>
      )}
    </div>
  );
}
