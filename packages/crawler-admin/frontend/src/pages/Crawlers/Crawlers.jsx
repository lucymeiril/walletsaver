import { useState, useEffect, useRef, useCallback, useMemo, memo } from 'react';
import useAdminStore from '../../stores/adminStore';
import { api } from '../../api/client';
import { Play, Settings, Plus, Power, X, CheckSquare, Square, Loader, ChevronDown, ChevronRight, RotateCcw } from 'lucide-react';
import styles from './Crawlers.module.css';

const CATEGORIES = [
  { key: 'all', label: '전체' },
  { key: 'mart', label: '마트' },
  { key: 'hotdeal', label: '핫딜' },
  { key: 'delivery', label: '배달' },
  { key: 'shopping', label: '쇼핑' },
  { key: 'government', label: '공공' },
  { key: 'location', label: '위치' },
];

const CATEGORY_LABELS = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.label]));

const STATUS_MAP = {
  active: { dot: styles.statusActive, label: '활성' },
  error: { dot: styles.statusError, label: '에러' },
  inactive: { dot: styles.statusInactive, label: '비활성' },
};

const TIMEOUT_SEC = 120;
// 지수 백오프 폴링: 활성 시 2초 → 최대 10초로 점진적 증가 (트래픽 절감)
const POLL_INTERVAL_BASE = 2000;
const POLL_INTERVAL_MAX = 10000;
const POLL_BACKOFF_FACTOR = 1.5;
const MAX_POLLS = 120;
const MART_LABELS = { emart: '이마트', homeplus: '홈플러스', lottemart: '롯데마트', costco: '코스트코' };
const SUCCESS_STATUSES = new Set(['success', 'partial_failure']);

function inferMart(crawler) {
  const haystack = `${crawler.id || ''} ${crawler.name || ''}`.toLowerCase();
  return ['emart', 'homeplus', 'lottemart', 'costco'].find((mart) => haystack.includes(mart)) || crawler.category || 'unknown';
}

function buildCounterSummary(data = {}, crawler) {
  const quality = data.quality_details || {};
  const mart = data.mart || inferMart(crawler);
  const errors = Array.isArray(data.errors) ? data.errors.length : (data.error_count ?? quality.error_count ?? 0);
  const found = data.total_collected ?? data.items_found ?? data.items_count ?? data.source_raw_count ?? quality.source_raw_count ?? data.total ?? 0;
  const valid = data.items_valid ?? data.valid_items ?? data.new_items ?? 0;
  const saved = data.items_saved ?? data.saved_items ?? 0;
  const duplicates = data.duplicates ?? data.duplicate_count ?? data.deduplicated_count ?? quality.deduplicated_count ?? 0;
  const filtered = data.filtered ?? data.filtered_count ?? quality.invalid_count ?? Math.max(0, found - (valid || saved || 0));
  return {
    mart,
    total: found,
    valid,
    saved,
    duplicates,
    filtered,
    errors,
  };
}

function CounterChips({ summary }) {
  if (!summary) return null;
  const label = MART_LABELS[summary.mart] || summary.mart;
  const chips = [
    ['총 수집', summary.total], ['유효', summary.valid], ['저장', summary.saved], ['중복', summary.duplicates], ['오류', summary.errors],
  ];
  return (
    <div className={styles.counterChips} aria-label={`${label} 수집 카운터`}>
      <span className={styles.counterMart}>{label}</span>
      {chips.map(([name, value]) => <span key={name} className={styles.counterChip}>{name} {Number(value || 0).toLocaleString()}</span>)}
    </div>
  );
}

function isValidUrl(str) {
  try {
    const url = new URL(str);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

function validateSettings(data) {
  const errors = {};
  if (data.target_url && !isValidUrl(data.target_url)) {
    errors.target_url = 'http:// 또는 https://로 시작하는 올바른 URL을 입력하세요';
  }
  if (data.delay < 0.5 || data.delay > 30) {
    errors.delay = '딜레이는 0.5~30초 범위여야 합니다';
  }
  if (!Number.isInteger(data.max_items) || data.max_items < 1 || data.max_items > 1000) {
    errors.max_items = '최대 항목 수는 1~1000 범위의 정수여야 합니다';
  }
  return errors;
}

// React.memo: 동일 runs 배열이면 리렌더 방지 — 카드 목록 성능 향상
const MiniTimeline = memo(function MiniTimeline({ runs }) {
  if (!runs || runs.length === 0) {
    return (
      <div className={styles.timeline} title="실행 이력 없음">
        {Array.from({ length: 5 }).map((_, i) => (
          <span key={i} className={styles.timelineDotEmpty} />
        ))}
      </div>
    );
  }
  const padded = [...Array(Math.max(0, 5 - runs.length)).fill(null), ...runs].slice(-5);
  return (
    <div className={styles.timeline}>
      {padded.map((run, i) => {
        if (!run) return <span key={i} className={styles.timelineDotEmpty} title="기록 없음" />;
        const isSuccess = run.status === 'success';
        return (
          <span
            key={i}
            className={isSuccess ? styles.timelineDotSuccess : styles.timelineDotFail}
            title={`${isSuccess ? '성공' : '실패'}${run.duration ? ` (${run.duration.toFixed(1)}초)` : ''}`}
          />
        );
      })}
    </div>
  );
});

function Spinner() {
  return <Loader size={14} className={styles.spinner} />;
}

export default function Crawlers() {
  const crawlerFilter = useAdminStore((s) => s.crawlerFilter);
  const setCrawlerFilter = useAdminStore((s) => s.setCrawlerFilter);
  const getFilteredCrawlers = useAdminStore((s) => s.getFilteredCrawlers);
  const toggleCrawlerStatus = useAdminStore((s) => s.toggleCrawlerStatus);
  const fetchCrawlers = useAdminStore((s) => s.fetchCrawlers);
  const runCrawler = useAdminStore((s) => s.runCrawler);
  const loading = useAdminStore((s) => s.crawlersLoading);
  const error = useAdminStore((s) => s.crawlersError);
  const filtered = getFilteredCrawlers();

  const [runStates, setRunStates] = useState({});
  const [settingsModal, setSettingsModal] = useState(null);
  const [settingsData, setSettingsData] = useState({ target_url: '', delay: 1, max_items: 100 });
  const [settingsErrors, setSettingsErrors] = useState({});
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [showAddInfo, setShowAddInfo] = useState(false);
  const [checkedIds, setCheckedIds] = useState(new Set());
  const [collapsedGroups, setCollapsedGroups] = useState(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [clockTick, setClockTick] = useState(() => Date.now());
  const pollRefs = useRef({});

  useEffect(() => {
    fetchCrawlers();
  }, [fetchCrawlers]);

  useEffect(() => {
    const hasRunning = Object.values(runStates).some((state) => state?.phase === 'running' || state?.phase === 'starting');
    if (!hasRunning) return undefined;
    const timer = setInterval(() => setClockTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [runStates]);

  useEffect(() => {
    return () => {
      // SSE 연결 및 폴링 타이머 모두 정리
      Object.values(pollRefs.current).forEach((ref) => {
        if (typeof ref === 'object' && ref.close) ref.close();
        else if (typeof ref === 'number') clearTimeout(ref);
      });
    };
  }, []);

  const setRunState = useCallback((id, state) => {
    setRunStates((prev) => ({ ...prev, [id]: state }));
  }, []);

  const clearRunState = useCallback((id, delay = 8000) => {
    setTimeout(() => setRunStates((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    }), delay);
  }, []);

  const startPolling = useCallback((id) => {
    // SSE 우선 시도 — 실시간 push로 폴링 대비 지연·트래픽 대폭 감소
    const startTime = Date.now();

    // Always fully close previous SSE/timer before opening new one
    const oldRef = pollRefs.current[id];
    if (oldRef) {
      if (typeof oldRef === 'object' && oldRef.close) oldRef.close();
      else if (typeof oldRef === 'number') clearTimeout(oldRef);
      delete pollRefs.current[id];
    }

    try {
      const sse = api.subscribeCrawlerStatus(id, {
        onData: (data) => {
          if (SUCCESS_STATUSES.has(data.status)) {
            const partial = data.status === 'partial_failure';
            setRunState(id, {
              phase: 'done',
              success: !partial,
              message: `${partial ? '⚠️ 부분 완료' : '✅ 크롤링 완료'} — ${data.items_found ?? 0}건 발견, ${data.items_saved ?? 0}건 저장 (${(data.duration ?? 0).toFixed(1)}초)`,
              summary: buildCounterSummary(data, { id }),
            });
            fetchCrawlers();
            clearRunState(id);
          } else if (data.status === 'failed') {
            setRunState(id, {
              phase: 'done',
              success: false,
              message: `❌ 크롤링 실패: ${(data.errors || []).join(', ') || '알 수 없는 오류'}`,
            });
            clearRunState(id);
          } else {
            setRunState(id, {
              phase: 'running',
              success: true,
              startedAt: startTime,
              message: `⏳ 크롤링 실행 중...${data.progress_stage ? ` (${data.progress_stage})` : ''}`,
              summary: buildCounterSummary(data, { id }),
            });
          }
        },
        onError: () => {
          // SSE 실패 시 지수 백오프 폴링으로 폴백
          startPollingFallback(id, startTime);
        },
        onComplete: () => {
          delete pollRefs.current[id];
        },
      });
      pollRefs.current[id] = sse;
    } catch {
      // SSE 미지원 시 지수 백오프 폴링 사용
      startPollingFallback(id, startTime);
    }
  }, [setRunState, clearRunState, fetchCrawlers]);

  // 지수 백오프 폴링: 2초 → 3초 → 4.5초 → ... 최대 10초 (SSE 폴백)
  const startPollingFallback = useCallback((id, startTime) => {
    let pollCount = 0;
    let currentInterval = POLL_INTERVAL_BASE;
    let consecutiveFailures = 0;

    const poll = async () => {
      pollCount++;
      let data = {};
      try {
        data = await api.getCrawlerStatus(id);
        consecutiveFailures = 0;
        if (SUCCESS_STATUSES.has(data.status)) {
          const partial = data.status === 'partial_failure';
          setRunState(id, {
            phase: 'done',
            success: !partial,
            message: `${partial ? '⚠️ 부분 완료' : '✅ 크롤링 완료'} — ${data.items_found ?? 0}건 발견, ${data.items_saved ?? 0}건 저장 (${(data.duration ?? 0).toFixed(1)}초)`,
            summary: buildCounterSummary(data, { id }),
          });
          delete pollRefs.current[id];
          fetchCrawlers();
          clearRunState(id);
          return;
        } else if (data.status === 'failed') {
          setRunState(id, {
            phase: 'done',
            success: false,
            message: `❌ 크롤링 실패: ${(data.errors || []).join(', ') || '알 수 없는 오류'}`,
          });
          delete pollRefs.current[id];
          clearRunState(id);
          return;
        }
      } catch {
        consecutiveFailures++;
        if (consecutiveFailures >= 3) {
          setRunState(id, {
            phase: 'running',
            success: false,
            message: `⚠️ 상태 확인 연결 불안정 (${consecutiveFailures}회 실패)`,
          });
        }
      }

      setRunState(id, {
        phase: 'running',
        success: true,
        startedAt: startTime,
        message: `⏳ 크롤링 실행 중...${data.progress_stage ? ` (${data.progress_stage})` : ''}`,
        summary: buildCounterSummary(data, { id }),
      });

      if (pollCount >= MAX_POLLS) {
        delete pollRefs.current[id];
        setRunState(id, {
          phase: 'done',
          success: false,
          message: `⏱ ${TIMEOUT_SEC}초 초과 — 타임아웃`,
        });
        clearRunState(id, 6000);
        return;
      }

      // 지수 백오프: 점진적으로 간격 증가
      currentInterval = Math.min(currentInterval * POLL_BACKOFF_FACTOR, POLL_INTERVAL_MAX);
      pollRefs.current[id] = setTimeout(poll, currentInterval);
    };

    pollRefs.current[id] = setTimeout(poll, currentInterval);
  }, [setRunState, clearRunState, fetchCrawlers]);

  const handleRun = useCallback(async (id) => {
    // Prevent duplicate runs — ignore if crawler is already running
    if (runStates[id]?.phase === 'running') return;

    setRunState(id, { phase: 'starting', success: true, startedAt: Date.now(), message: '크롤러 실행 요청 중...' });
    const result = await runCrawler(id);
    if (result) {
      setRunState(id, { phase: 'running', success: true, startedAt: Date.now(), message: '⏳ 크롤링 실행 중...', summary: buildCounterSummary(result, { id }) });
      startPolling(id);
    } else {
      setRunState(id, { phase: 'done', success: false, message: '❌ 실행 실패: 요청을 처리할 수 없습니다.' });
      clearRunState(id, 4000);
    }
  }, [runStates, runCrawler, setRunState, startPolling, clearRunState]);

  const handleRetryLastFailed = useCallback(async (crawler) => {
    const id = crawler.id;
    setRunState(id, { phase: 'starting', success: true, message: '🔁 마지막 실패 run을 찾는 중...' });
    try {
      const data = await api.retryLastFailed(crawler.id);
      setRunState(id, {
        phase: 'running',
        success: true,
        message: `🔁 재시도 시작 — 새 run: ${data.run_id || '(생성됨)'}`,
      });
      startPolling(id);
    } catch (err) {
      const msg = err?.status === 404
        ? '재시도할 실패 run이 없습니다. (마지막 실행이 성공이거나 기록이 없음)'
        : (err?.message || '재시도 실패');
      setRunState(id, { phase: 'done', success: false, message: `❌ ${msg}` });
      clearRunState(id, 5000);
    }
  }, [setRunState, startPolling, clearRunState]);

  const handleBulkRun = useCallback(async () => {
    if (checkedIds.size === 0) return;
    setBulkRunning(true);
    const ids = [...checkedIds];
    try {
      const resp = await api.bulkRunCrawlers(ids);
      const results = resp.results || [];
      for (const r of results) {
        if (r.status === 'running') {
          setRunState(r.crawler_id, { phase: 'running', success: true, startedAt: Date.now(), message: '⏳ 크롤링 실행 중...', summary: buildCounterSummary(r, { id: r.crawler_id }) });
          startPolling(r.crawler_id);
        } else {
          setRunState(r.crawler_id, { phase: 'done', success: false, message: r.message || r.error || '실행 실패' });
          clearRunState(r.crawler_id, 4000);
        }
      }
    } catch {
      for (const id of ids) {
        setRunState(id, { phase: 'done', success: false, message: '벌크 실행에 실패했습니다. 잠시 후 다시 시도해 주세요.' });
        clearRunState(id, 4000);
      }
    }
    setBulkRunning(false);
    setCheckedIds(new Set());
  }, [checkedIds, setRunState, startPolling, clearRunState]);

  const toggleCheck = useCallback((id) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAllInGroup = useCallback((ids) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      const allChecked = ids.every((id) => next.has(id));
      if (allChecked) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }, []);

  const toggleCollapse = useCallback((cat) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }, []);

  const openSettings = async (crawlerId) => {
    setSettingsModal(crawlerId);
    setSettingsLoading(true);
    setSettingsErrors({});
    try {
      const data = await api.getCrawlerSettings(crawlerId);
      setSettingsData({
        target_url: data.target_url || '',
        delay: data.delay ?? 1,
        max_items: data.max_items ?? 100,
      });
    } catch {
      setSettingsData({ target_url: '', delay: 1, max_items: 100 });
    }
    setSettingsLoading(false);
  };

  const saveSettings = async () => {
    if (!settingsModal) return;
    const errs = validateSettings(settingsData);
    if (Object.keys(errs).length > 0) {
      setSettingsErrors(errs);
      return;
    }
    setSettingsLoading(true);
    try {
      await api.updateCrawlerSettings(settingsModal, settingsData);
      setSettingsModal(null);
      setSettingsErrors({});
    } catch {
      alert('설정 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.');
    }
    setSettingsLoading(false);
  };

  const formatTime = (iso) => {
    if (!iso) return '-';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '-';
    return d.toLocaleString('ko-KR', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const grouped = useMemo(() => {
    if (crawlerFilter !== 'all') return null;
    const groups = {};
    for (const c of filtered) {
      const cat = c.category || 'etc';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(c);
    }
    const order = ['mart', 'hotdeal', 'delivery', 'shopping', 'government', 'location', 'etc'];
    return order.filter((k) => groups[k]).map((k) => ({ key: k, label: CATEGORY_LABELS[k] || k, crawlers: groups[k] }));
  }, [filtered, crawlerFilter]);

  const renderCard = (crawler) => {
    const st = STATUS_MAP[crawler.status] || STATUS_MAP.inactive;
    const rs = runStates[crawler.id];
    const isRunning = rs?.phase === 'running' || rs?.phase === 'starting';
    const isChecked = checkedIds.has(crawler.id);
    const recent = crawler.recentRuns || [];
    const lastRun = recent.length > 0 ? recent[recent.length - 1] : null;
    const lastRunFailed = lastRun && (lastRun.status === 'failed' || lastRun.status === 'error');
    const elapsedSec = isRunning && rs?.startedAt ? Math.max(1, Math.floor((clockTick - rs.startedAt) / 1000)) : null;
    const counterSummary = rs?.summary || (isRunning ? buildCounterSummary({}, crawler) : null);

    return (
      <div key={crawler.id} className={`${styles.card} ${isRunning ? styles.cardRunning : ''}`}>
        <div className={styles.cardHeader}>
          <div className={styles.cardTitleRow}>
            <button
              className={styles.checkbox}
              onClick={() => toggleCheck(crawler.id)}
              title={isChecked ? '선택 해제' : '선택'}
            >
              {isChecked ? <CheckSquare size={16} /> : <Square size={16} />}
            </button>
            <div className={styles.cardTitle}>
              <span className={`${styles.statusDot} ${st.dot}`} />
              {crawler.name}
            </div>
          </div>
          <span className={styles.category}>{crawler.category}</span>
        </div>

        <div className={styles.cardMeta}>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>난이도</span>
            <span className={styles.metaValue}>{crawler.difficulty}</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>마지막 크롤</span>
            <span className={styles.metaValue}>{formatTime(crawler.lastCrawl)}</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>성공률</span>
            <span className={styles.metaValue}>{crawler.successRate}%</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>총 실행 횟수</span>
            <span className={styles.metaValue}>{(crawler.totalRuns || 0).toLocaleString()}회</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>최근 실행</span>
            <MiniTimeline runs={crawler.recentRuns} />
          </div>
        </div>

        {rs && (
          <div className={`${styles.runResult} ${rs.success ? styles.runResultSuccess : styles.runResultFail}`}>
            <div className={styles.runStatusLine}>
              {isRunning && <Spinner />}
              <span>{rs.message}</span>
              {elapsedSec != null && <span className={styles.elapsedBadge}>{elapsedSec}초 경과</span>}
            </div>
            <CounterChips summary={counterSummary} />
          </div>
        )}

        <div className={styles.cardActions}>
          <button
            className={styles.actionBtn}
            title="수동 실행"
            onClick={() => handleRun(crawler.id)}
            disabled={isRunning}
          >
            {isRunning ? <Spinner /> : <Play size={14} />}
            {isRunning ? '실행중' : '실행'}
          </button>
          <button className={styles.actionBtn} title="설정" onClick={() => openSettings(crawler.id)}>
            <Settings size={14} />
            설정
          </button>
          <button
            className={crawler.status === 'active' ? styles.toggleBtnActive : styles.toggleBtn}
            onClick={() => toggleCrawlerStatus(crawler.id)}
            title={crawler.status === 'active' ? '비활성화' : '활성화'}
          >
            <Power size={14} />
            {crawler.status === 'active' ? '활성' : '비활성'}
          </button>
          {lastRunFailed && (
            <button
              className={styles.actionBtn}
              title="마지막 실패 run 재시도"
              aria-label={`${crawler.name} 마지막 실패 재시도`}
              data-testid={`retry-last-failed-${crawler.id}`}
              onClick={() => handleRetryLastFailed(crawler)}
              disabled={isRunning}
              style={{ marginLeft: 'auto', background: '#fef2f2', color: '#dc2626', borderColor: '#fecaca' }}
            >
              <RotateCcw size={14} />
              실패 재시도
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.pageTitle}>크롤러 관리</h1>
        <div className={styles.actions}>
          {checkedIds.size > 0 && (
            <button
              className={styles.bulkRunBtn}
              onClick={handleBulkRun}
              disabled={bulkRunning}
            >
              {bulkRunning ? <Spinner /> : <Play size={16} />}
              선택 실행 ({checkedIds.size})
            </button>
          )}
          <button className={styles.addBtn} onClick={() => setShowAddInfo(true)}>
            <Plus size={16} />
            크롤러 추가
          </button>
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          ⚠️ {error.startsWith('HTTP') ? '서버와 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.' : error}
        </div>
      )}

      <div className={styles.filters}>
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            className={crawlerFilter === cat.key ? styles.filterBtnActive : styles.filterBtn}
            onClick={() => setCrawlerFilter(cat.key)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {loading && filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text3, #64748b)' }}>
          <Loader size={24} className={styles.spinner} style={{ marginBottom: '8px' }} />
          <div>크롤러 목록을 불러오는 중...</div>
        </div>
      )}

      {filtered.length === 0 && !loading && (
        <div className={styles.emptyState}>
          {error ? '크롤러 목록을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.' : '등록된 크롤러가 없습니다'}
        </div>
      )}

      {/* 카테고리 그룹 모드 (전체 필터) */}
      {grouped && grouped.map((group) => {
        const isCollapsed = collapsedGroups.has(group.key);
        const groupIds = group.crawlers.map((c) => c.id);
        const allChecked = groupIds.length > 0 && groupIds.every((id) => checkedIds.has(id));
        return (
          <div key={group.key} className={styles.group}>
            <div className={styles.groupHeader}>
              <button className={styles.groupToggle} onClick={() => toggleCollapse(group.key)}>
                {isCollapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
                <span className={styles.groupLabel}>{group.label}</span>
                <span className={styles.groupCount}>{group.crawlers.length}</span>
              </button>
              <button
                className={styles.groupCheckAll}
                onClick={() => toggleAllInGroup(groupIds)}
                title={allChecked ? '모두 해제' : '모두 선택'}
              >
                {allChecked ? <CheckSquare size={14} /> : <Square size={14} />}
              </button>
            </div>
            {!isCollapsed && (
              <div className={styles.grid}>
                {group.crawlers.map(renderCard)}
              </div>
            )}
          </div>
        );
      })}

      {/* 특정 카테고리 필터 모드 */}
      {!grouped && (
        <div className={styles.grid}>
          {filtered.map(renderCard)}
        </div>
      )}

      {/* Settings Modal */}
      {settingsModal && (
        <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && setSettingsModal(null)}>
          <div className={styles.modal}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>크롤러 설정 — {settingsModal}</h3>
              <button onClick={() => { setSettingsModal(null); setSettingsErrors({}); }} className={styles.modalClose}>
                <X size={20} />
              </button>
            </div>

            {settingsLoading ? (
              <div className={styles.modalLoading}>로딩 중...</div>
            ) : (
              <>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>대상 URL</label>
                  <input
                    type="text"
                    value={settingsData.target_url}
                    onChange={(e) => {
                      setSettingsData({ ...settingsData, target_url: e.target.value });
                      setSettingsErrors((prev) => ({ ...prev, target_url: undefined }));
                    }}
                    className={`${styles.formInput} ${settingsErrors.target_url ? styles.formInputError : ''}`}
                    placeholder="https://example.com"
                  />
                  {settingsErrors.target_url && <span className={styles.formError}>{settingsErrors.target_url}</span>}
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>요청 딜레이 (초) <span className={styles.formHint}>0.5 ~ 30</span></label>
                  <input
                    type="number"
                    min="0.5"
                    max="30"
                    step="0.5"
                    value={settingsData.delay}
                    onChange={(e) => {
                      setSettingsData({ ...settingsData, delay: parseFloat(e.target.value) || 0 });
                      setSettingsErrors((prev) => ({ ...prev, delay: undefined }));
                    }}
                    className={`${styles.formInput} ${settingsErrors.delay ? styles.formInputError : ''}`}
                  />
                  {settingsErrors.delay && <span className={styles.formError}>{settingsErrors.delay}</span>}
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>최대 수집 항목 수 <span className={styles.formHint}>1 ~ 1000</span></label>
                  <input
                    type="number"
                    min="1"
                    max="1000"
                    value={settingsData.max_items}
                    onChange={(e) => {
                      setSettingsData({ ...settingsData, max_items: parseInt(e.target.value) || 0 });
                      setSettingsErrors((prev) => ({ ...prev, max_items: undefined }));
                    }}
                    className={`${styles.formInput} ${settingsErrors.max_items ? styles.formInputError : ''}`}
                  />
                  {settingsErrors.max_items && <span className={styles.formError}>{settingsErrors.max_items}</span>}
                </div>
                <div className={styles.modalActions}>
                  <button onClick={() => { setSettingsModal(null); setSettingsErrors({}); }} className={styles.cancelBtn}>취소</button>
                  <button onClick={saveSettings} disabled={settingsLoading} className={styles.saveBtn}>저장</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Add Crawler Info Modal */}
      {showAddInfo && (
        <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && setShowAddInfo(false)}>
          <div className={styles.modal} style={{ maxWidth: '500px' }}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>크롤러 추가 방법</h3>
              <button onClick={() => setShowAddInfo(false)} className={styles.modalClose}>
                <X size={20} />
              </button>
            </div>
            <div className={styles.addInfo}>
              <p>새 크롤러를 추가하려면 <code className={styles.inlineCode}>plugin.yaml</code> 파일을 생성하세요:</p>
              <ol>
                <li><code className={styles.inlineCode}>crawlers/[카테고리]/[크롤러명]/</code> 디렉토리 생성</li>
                <li><code className={styles.inlineCode}>plugin.yaml</code> 파일 작성 (이름, 버전, 대상 URL 등)</li>
                <li><code className={styles.inlineCode}>crawler.py</code> 파일에 CrawlerContract 구현</li>
                <li>서버 재시작 시 자동 등록됨</li>
              </ol>
              <pre className={styles.codeBlock}>
{`name: my_crawler
display_name: 내 크롤러
category: mart
version: 1.0.0
description: 설명
target:
  url: https://example.com
  difficulty: 2
  strategy: requests
schedule:
  cron: "0 */6 * * *"`}
              </pre>
            </div>
            <div className={styles.modalActions} style={{ justifyContent: 'flex-end' }}>
              <button onClick={() => setShowAddInfo(false)} className={styles.saveBtn}>확인</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
