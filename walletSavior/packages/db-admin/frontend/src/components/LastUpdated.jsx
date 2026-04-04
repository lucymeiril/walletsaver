import { useState, useEffect } from 'react';
import { Clock, RefreshCw } from 'lucide-react';

function formatRelativeTime(timestamp) {
  if (!timestamp) return null;
  const diff = Math.floor((Date.now() - timestamp) / 1000);
  if (diff < 10) return '방금 전';
  if (diff < 60) return `${diff}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

export default function LastUpdated({ timestamp, onRefresh, isLoading }) {
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => forceUpdate(n => n + 1), 30000);
    return () => clearInterval(interval);
  }, []);

  const label = formatRelativeTime(timestamp);
  const isStale = timestamp && (Date.now() - timestamp) > 5 * 60 * 1000;

  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
      fontSize: '0.8rem', color: isStale ? 'var(--warning, #e67e22)' : 'var(--text3, #999)',
    }}>
      <Clock size={13} />
      <span>{label ? `마지막 업데이트: ${label}` : '아직 로드되지 않음'}</span>
      {isStale && <span style={{ fontWeight: 600 }}>(오래됨)</span>}
      {onRefresh && (
        <button
          onClick={onRefresh}
          disabled={isLoading}
          title="새로고침"
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            padding: 2, display: 'inline-flex', color: 'inherit',
          }}
        >
          <RefreshCw
            size={13}
            style={isLoading ? { animation: 'spin 1s linear infinite' } : {}}
          />
        </button>
      )}
    </div>
  );
}
