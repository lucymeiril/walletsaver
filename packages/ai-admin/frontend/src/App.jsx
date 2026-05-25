import { useCallback, useEffect, useState } from 'react';
import BackendStatusBanner from './BackendStatusBanner.jsx';
import HomePage from './HomePage.jsx';
import ReviewPage from './ReviewPage.jsx';
import AdvancedPage from './AdvancedPage.jsx';
// 외부 분류 워크플로우 export 패널 (정상 운영 경로).
// LivePipelinePanel(라이브 AI 처리, 보류 중)과는 별개.
import ExternalExportPanel from './ExternalExportPanel.jsx';

/**
 * 사용자 직격 비판에 대한 응답:
 *  1. "탭 분리만 한다고 UI/UX가 개선이 안 됨" → 3 페이지(홈/검수/고급)로 축소.
 *  2. "AI 제안 비우기 어디감? 34,300건 못 비워?" → 홈/검수 양쪽에서 1-click 비우기 wizard.
 *  3. "매칭 누적 — 뭘 어쩌라는 건지" → 의미가 명확한 KPI 3장으로 압축 + 상세는 고급으로.
 *  4. "직접 검수 1-2 click 어긋남" → ReviewPage: 카드 5필드, Enter 승인, X 반려, J/K 이동, 무한 스크롤.
 *  5. "고급 탭이 사람이 쓸 수 있는 UI/UX인지 모르겠음" → AdvancedPage 전면 rewrite (rd4):
 *     3-step 보드 + 에러 분류별 next-action + JobProgressBar + 키보드 R/E/Esc.
 *  6. 디자인 → Pretendard, 회색 70% + 보라색 강조, 라이트/다크 토글.
 */

const TABS = [
  { id: 'home', label: '홈' },
  // 외부 분류 탭: 권장 경로 (라이브 AI 보류 중이므로 홈 바로 다음 배치)
  { id: 'export', label: '외부 분류' },
  { id: 'review', label: '검수' },
  { id: 'advanced', label: '고급' },
];

function ThemeToggle() {
  const [theme, setTheme] = useState(() => {
    if (typeof window === 'undefined') return 'dark';
    return localStorage.getItem('ai-admin-theme') || 'dark';
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('ai-admin-theme', theme); } catch (_) {}
  }, [theme]);
  return (
    <button
      type="button"
      className="icon-btn theme-toggle"
      onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      title={theme === 'dark' ? '라이트 모드로' : '다크 모드로'}
      aria-label="테마 전환"
    >
      {theme === 'dark' ? '☾' : '☀'}
    </button>
  );
}

export default function App() {
  const [tab, setTab] = useState('home');

  const goAdvanced = useCallback((anchor) => {
    setTab('advanced');
    if (anchor) {
      setTimeout(() => {
        document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 60);
    }
  }, []);
  const goReview = useCallback(() => setTab('review'), []);

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden>◆</span>
          <div>
            <h1>WalletSavior AI 관리</h1>
            <p className="subtitle">필요한 것만. 나머지는 고급으로.</p>
          </div>
        </div>
        <ThemeToggle />
      </header>

      <BackendStatusBanner />

      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`tab ${tab === t.id ? 'tab-active' : ''}`}
            onClick={() => setTab(t.id)}
            data-testid={`tab-${t.id}`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="tab-panels">
        {tab === 'home' && <HomePage onGoReview={goReview} onGoAdvanced={goAdvanced} />}
        {/* 외부 분류: ExternalExportPanel (정상 운영).
            LivePipelinePanel(보류 중)은 고급 탭의 AdvancedPage 에 별도 유지. */}
        {tab === 'export' && <ExternalExportPanel />}
        {tab === 'review' && <ReviewPage />}
        {tab === 'advanced' && <AdvancedPage onGoReview={goReview} />}
      </main>
    </div>
  );
}
