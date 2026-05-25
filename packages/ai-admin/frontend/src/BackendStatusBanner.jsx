import { useEffect, useState } from 'react';

/**
 * 사용자 비판 해소: "메트릭 0 = 정상" 가정 금지. 백엔드 끊김/HTTP 502/timeout을
 * 빈 데이터와 구분해서 *위* 한 줄에 강제 표시한다.
 */
export default function BackendStatusBanner({ onRetry }) {
  const [state, setState] = useState({ phase: 'loading', detail: null, lastOkAt: null });

  async function probe() {
    setState((p) => ({ ...p, phase: 'loading' }));
    try {
      const t0 = performance.now();
      const res = await fetch('/health', { cache: 'no-store' });
      if (!res.ok) {
        setState({ phase: 'error', detail: `HTTP ${res.status}`, lastOkAt: null });
        return false;
      }
      const body = await res.json().catch(() => ({}));
      setState({
        phase: 'ok',
        detail: `uptime ${body.uptime_seconds ?? '?'}s · ${Math.round(performance.now() - t0)}ms`,
        lastOkAt: new Date(),
      });
      return true;
    } catch (err) {
      setState({ phase: 'down', detail: err.message || '연결 불가', lastOkAt: null });
      return false;
    }
  }

  useEffect(() => {
    probe();
    const id = setInterval(probe, 15000);
    return () => clearInterval(id);
  }, []);

  if (state.phase === 'ok') {
    return (
      <div className="backend-banner backend-banner-ok" role="status" data-testid="backend-banner">
        <span className="backend-dot dot-ok" aria-hidden />
        <span><strong>백엔드 정상</strong> · {state.detail}</span>
      </div>
    );
  }
  if (state.phase === 'loading') {
    return (
      <div className="backend-banner backend-banner-warn" role="status" data-testid="backend-banner">
        <span className="backend-dot dot-warn" aria-hidden />
        <span>백엔드 확인 중…</span>
      </div>
    );
  }
  const isDown = state.phase === 'down';
  return (
    <div className="backend-banner backend-banner-err" role="alert" data-testid="backend-banner">
      <span className="backend-dot dot-err" aria-hidden />
      <div>
        <strong>{isDown ? '백엔드 연결 끊김' : '백엔드 응답 오류'}</strong>
        <div className="muted">
          {state.detail} · 아래 메트릭의 "0"은 *정상 0*이 아니라 *조회 실패*입니다.
        </div>
      </div>
      <button
        type="button"
        className="primary-button"
        onClick={() => {
          probe();
          onRetry?.();
        }}
      >
        다시 시도
      </button>
    </div>
  );
}
