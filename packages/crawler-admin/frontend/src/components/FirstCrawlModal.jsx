import { useEffect, useState } from 'react';
import { X, Play, Loader } from 'lucide-react';
import useAdminStore from '../stores/adminStore';

/**
 * 첫 크롤 실행 모달 — 마트 선택 후 즉시 trigger.
 * 헌법: "초심자도 이용하기 쉽게", 메트릭 0 시 다음 액션 명시.
 */
export default function FirstCrawlModal({ isOpen, onClose, onLaunched }) {
  const crawlers = useAdminStore((s) => s.crawlers);
  const fetchCrawlers = useAdminStore((s) => s.fetchCrawlers);
  const runCrawler = useAdminStore((s) => s.runCrawler);

  const [selectedId, setSelectedId] = useState(null);
  const [launching, setLaunching] = useState(false);
  const [resultMsg, setResultMsg] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);

  useEffect(() => {
    if (isOpen && crawlers.length === 0) {
      fetchCrawlers();
    }
    if (!isOpen) {
      setSelectedId(null);
      setLaunching(false);
      setResultMsg(null);
      setErrorMsg(null);
    }
  }, [isOpen, crawlers.length, fetchCrawlers]);

  // 마트 카테고리 우선 표시
  const martCrawlers = crawlers.filter((c) => c.category === 'mart' || /이마트|홈플러스|롯데|코스트코/.test(c.name));
  const candidates = martCrawlers.length > 0 ? martCrawlers : crawlers;

  if (!isOpen) return null;

  const handleLaunch = async () => {
    if (!selectedId) {
      setErrorMsg('실행할 크롤러를 선택해 주세요.');
      return;
    }
    setLaunching(true);
    setErrorMsg(null);
    setResultMsg(null);
    const result = await runCrawler(selectedId);
    setLaunching(false);
    if (result) {
      setResultMsg(`"${selectedId}" 실행을 시작했어요. 잠시 후 대시보드가 업데이트됩니다.`);
      if (onLaunched) onLaunched(selectedId, result);
    } else {
      setErrorMsg('크롤러 실행에 실패했어요. 백엔드 연결 또는 권한을 확인해 주세요.');
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="첫 크롤 실행"
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        background: 'var(--surface, #1e293b)', borderRadius: 12,
        width: '100%', maxWidth: 520, padding: 24, color: 'var(--text, #f1f5f9)',
        border: '1px solid var(--border, rgba(148,163,184,0.18))',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: '1.1rem' }}>🚀 첫 크롤 실행하기</h2>
          <button onClick={onClose} aria-label="닫기" style={{ background: 'transparent', border: 0, color: 'var(--text2)', cursor: 'pointer' }}>
            <X size={18} />
          </button>
        </div>
        <p style={{ margin: '0 0 14px', color: 'var(--text2, #cbd5e1)', fontSize: '.9rem' }}>
          마트(또는 크롤러)를 선택하면 즉시 백그라운드 실행을 트리거합니다.
        </p>

        {crawlers.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--text3)' }}>
            <Loader size={20} className="spin" /> 크롤러 목록 로딩 중…
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 8, maxHeight: 280, overflowY: 'auto', marginBottom: 14 }}>
            {candidates.map((c) => (
              <label
                key={c.id}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '10px 12px', borderRadius: 8, cursor: 'pointer',
                  border: `1px solid ${selectedId === c.id ? 'var(--accent, #38bdf8)' : 'var(--border, rgba(148,163,184,0.18))'}`,
                  background: selectedId === c.id ? 'rgba(56,189,248,0.08)' : 'transparent',
                }}
              >
                <input
                  type="radio"
                  name="firstCrawl"
                  value={c.id}
                  checked={selectedId === c.id}
                  onChange={() => setSelectedId(c.id)}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{c.name}</div>
                  <div style={{ fontSize: '.75rem', color: 'var(--text3)' }}>
                    {c.category} · 마지막 실행: {c.lastCrawl || '없음'}
                  </div>
                </div>
              </label>
            ))}
          </div>
        )}

        {errorMsg && (
          <div role="alert" style={{
            padding: '8px 12px', borderRadius: 6,
            background: 'rgba(248,113,113,0.12)', color: '#fca5a5',
            fontSize: '.85rem', marginBottom: 10,
          }}>{errorMsg}</div>
        )}
        {resultMsg && (
          <div role="status" style={{
            padding: '8px 12px', borderRadius: 6,
            background: 'rgba(74,222,128,0.12)', color: '#86efac',
            fontSize: '.85rem', marginBottom: 10,
          }}>{resultMsg}</div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button
            onClick={onClose}
            style={{
              padding: '0.5rem 1rem', borderRadius: 8,
              border: '1px solid var(--border, rgba(148,163,184,0.2))',
              background: 'transparent', color: 'var(--text2)', cursor: 'pointer',
            }}
          >
            취소
          </button>
          <button
            onClick={handleLaunch}
            disabled={launching || !selectedId}
            style={{
              padding: '0.5rem 1.1rem', borderRadius: 8,
              border: 0, background: 'var(--accent, #38bdf8)',
              color: '#0b1220', cursor: launching ? 'wait' : 'pointer',
              fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6,
              opacity: launching || !selectedId ? 0.7 : 1,
            }}
          >
            {launching ? <Loader size={14} /> : <Play size={14} />}
            {launching ? '실행 중…' : '즉시 실행'}
          </button>
        </div>
      </div>
    </div>
  );
}
