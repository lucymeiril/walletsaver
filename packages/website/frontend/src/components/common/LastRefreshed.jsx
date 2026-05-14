import { useState, useEffect } from 'react';
import { RefreshCw } from 'lucide-react';
import s from './LastRefreshed.module.css';

function formatElapsed(ms) {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 10) return '방금 전';
  if (seconds < 60) return `${seconds}초 전`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  return `${hours}시간 전`;
}

/**
 * "마지막 업데이트: N초 전" 표시 + 수동 새로고침 버튼.
 * 15초마다 상대 시간을 갱신한다.
 */
export default function LastRefreshed({ timestamp, onRefresh, loading = false, className = '' }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!timestamp) return;
    const id = setInterval(() => setTick((t) => t + 1), 15_000);
    return () => clearInterval(id);
  }, [timestamp]);

  if (!timestamp) return null;

  const elapsed = Date.now() - timestamp;

  return (
    <div className={`${s.wrapper} ${className}`} aria-live="polite">
      <span className={s.text}>마지막 업데이트: {formatElapsed(elapsed)}</span>
      {onRefresh && (
        <button
          className={s.refreshBtn}
          onClick={onRefresh}
          disabled={loading}
          aria-label="새로고침"
          title="새로고침"
        >
          <RefreshCw size={14} className={loading ? s.spin : ''} />
        </button>
      )}
    </div>
  );
}
