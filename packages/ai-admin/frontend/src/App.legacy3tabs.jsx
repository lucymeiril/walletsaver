import { useCallback, useState } from 'react';
import ProvidersPanel from './ProvidersPanel.jsx';
import JobsPanel from './JobsPanel.jsx';
import PromptPacksPanel from './PromptPacksPanel.jsx';
import ReviewQueuePanel from './ReviewQueuePanel.jsx';
import MatchMonitorPanel from './MatchMonitorPanel.jsx';
import PendingEscalationPanel from './PendingEscalationPanel.jsx';
import BackendStatusBanner from './BackendStatusBanner.jsx';
import LivePipelinePanel from './LivePipelinePanel.jsx';

/**
 * 사용자 비판 해소 (App.jsx 재설계):
 *  1. 동일 워크플로 4중 중복 → 단일 LivePipelinePanel (3-step)
 *  2. 정보 과부하 → 탭 구조: 홈/검수/매칭/알람/고급. 첫 화면 카드 수 ~50 → ~10
 *  3. 에러 인지 불가 → 최상단 BackendStatusBanner가 "백엔드 끊김"을 명시
 *  4. 고급/초보 분리 → 전문 패널은 고급 탭으로 격리
 *  5. 묶음 처리 진입점 불명 → 홈 hero에 "AI 처리 가동" / "검수·발행 열기" 단일 버튼
 */

const TABS = [
  { id: 'home', label: '🏠 홈', help: '오늘 할 일과 라이브 파이프라인' },
  { id: 'review', label: '📋 검수·발행', help: 'AI 제안 검수와 묶음 발행' },
  { id: 'match', label: '📊 매칭 누적', help: 'ProductMatch / LearnedKnowledge 누적 통계' },
  { id: 'alarm', label: '🔔 알람', help: 'pending_db_review escalation 등 정체 알람' },
  { id: 'advanced', label: '⚙️ 고급', help: 'provider · 잡 큐 · 프롬프트 · 헬스' },
];

function HealthInline() {
  return (
    <section className="panel" id="advanced-health">
      <h2>헬스체크</h2>
      <div className="muted">
        백엔드 상태는 화면 최상단 배너에서 실시간으로 확인합니다.
        본 섹션은 호환을 위해 유지됩니다.
      </div>
    </section>
  );
}

export default function App() {
  const [tab, setTab] = useState('home');

  const openAdvanced = useCallback((target) => {
    setTab('advanced');
    window.setTimeout(() => {
      if (target) {
        document.querySelector(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 50);
  }, []);

  const openReview = useCallback(() => {
    setTab('review');
    window.setTimeout(() => {
      document.querySelector('.app-tab-panels')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>🤖 WalletSavior AI 관리</h1>
        <p className="subtitle">필요한 정보만 한 눈에. 자세한 전문 옵션은 고급 탭으로.</p>
      </header>

      <BackendStatusBanner />

      <nav className="app-tabs" role="tablist" aria-label="주 탐색 탭">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`tabpanel-${t.id}`}
            id={`tab-${t.id}`}
            className={`app-tab ${tab === t.id ? 'app-tab-active' : ''}`}
            onClick={() => setTab(t.id)}
            title={t.help}
            data-testid={`tab-${t.id}`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="app-tab-panels">
        {tab === 'home' && (
          <div role="tabpanel" id="tabpanel-home" aria-labelledby="tab-home">
            <LivePipelinePanel onGoToReview={openReview} onGoToAdvanced={openAdvanced} />
          </div>
        )}
        {tab === 'review' && (
          <div role="tabpanel" id="tabpanel-review" aria-labelledby="tab-review">
            <ReviewQueuePanel />
          </div>
        )}
        {tab === 'match' && (
          <div role="tabpanel" id="tabpanel-match" aria-labelledby="tab-match">
            <MatchMonitorPanel />
          </div>
        )}
        {tab === 'alarm' && (
          <div role="tabpanel" id="tabpanel-alarm" aria-labelledby="tab-alarm">
            <PendingEscalationPanel />
          </div>
        )}
        {tab === 'advanced' && (
          <div role="tabpanel" id="tabpanel-advanced" aria-labelledby="tab-advanced">
            <HealthInline />
            <div id="advanced-providers" className="anchor-offset"><ProvidersPanel /></div>
            <div id="advanced-jobs" className="anchor-offset"><JobsPanel /></div>
            <PromptPacksPanel />
          </div>
        )}
      </div>
    </div>
  );
}
