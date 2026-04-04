import { Loader2 } from 'lucide-react';

export function LoadingBar({ message = '불러오는 중...' }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.5rem',
      padding: '0.75rem 1rem', background: 'var(--bg2, #f8f9fa)',
      borderRadius: 8, color: 'var(--text3, #888)', fontSize: '0.9rem',
    }}>
      <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
      {message}
    </div>
  );
}

export function LoadingOverlay({ message = '처리 중...' }) {
  return (
    <div style={{
      position: 'absolute', inset: 0, display: 'flex',
      alignItems: 'center', justifyContent: 'center',
      background: 'rgba(255,255,255,0.8)', zIndex: 10, borderRadius: 8,
    }}>
      <LoadingBar message={message} />
    </div>
  );
}
