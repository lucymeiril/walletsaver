import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckSquare, ChevronDown, ChevronRight, Loader, Play, RotateCcw, Square } from 'lucide-react';

import { api } from '../../api/client';
import useAdminStore from '../../stores/adminStore';
import styles from './Crawlers.module.css';

const CATEGORIES = [
  { key: 'all', label: '전체' },
  { key: 'mart', label: '마트' },
  { key: 'shopping', label: '쇼핑' },
  { key: 'hotdeal', label: '핫딜' },
];

const CATEGORY_LABELS = Object.fromEntries(CATEGORIES.map((item) => [item.key, item.label]));
const STATUS_MAP = {
  active: { dot: styles.statusActive, label: '활성' },
  error: { dot: styles.statusError, label: '에러' },
  inactive: { dot: styles.statusInactive, label: '비활성' },
};

const POLL_INTERVAL_MS = 2000;
const MART_LABELS = {
  emart: '이마트',
  homeplus: '홈플러스',
  lottemart: '롯데마트',
  costco: '코스트코',
};
const SUCCESS_STATUSES = new Set(['success', 'partial_failure']);

function inferMart(crawler) {
  const haystack = `${crawler.id || ''} ${crawler.name || ''}`.toLowerCase();
  return ['emart', 'homeplus', 'lottemart', 'costco'].find((mart) => haystack.includes(mart))
    || crawler.category
    || 'unknown';
}

function buildCounterSummary(data = {}, crawler) {
  const quality = data.quality_details || {};
  const mart = data.mart || inferMart(crawler);
  const errors = Array.isArray(data.errors)
    ? data.errors.length
    : (data.error_count ?? quality.error_count ?? 0);
  const found = data.total_collected
    ?? data.items_found
    ?? data.items_count
    ?? data.source_raw_count
    ?? quality.source_raw_count
    ?? data.total
    ?? 0;
  const valid = data.items_valid ?? data.valid_items ?? data.new_items ?? 0;
  const saved = data.items_saved ?? data.saved_items ?? 0;
  const duplicates = data.duplicates
    ?? data.duplicate_count
    ?? data.deduplicated_count
    ?? quality.deduplicated_count
    ?? 0;

  return { mart, total: found, valid, saved, duplicates, errors };
}

function CounterChips({ summary }) {
  if (!summary) return null;
  const label = MART_LABELS[summary.mart] || summary.mart;
  const chips = [
    ['총 수집', summary.total],
    ['유효', summary.valid],
    ['저장', summary.saved],
    ['중복', summary.duplicates],
    ['오류', summary.errors],
  ];
  return (
    <div className={styles.counterChips} aria-label={`${label} 수집 카운터`}>
      <span className={styles.counterMart}>{label}</span>
      {chips.map(([name, value]) => (
        <span key={name} className={styles.counterChip}>
          {name} {Number(value || 0).toLocaleString()}
        </span>
      ))}
    </div>
  );
}

const MiniTimeline = memo(function MiniTimeline({ runs }) {
  if (!runs || runs.length === 0) {
    return (
      <div className={styles.timeline} title="실행 이력 없음">
        {Array.from({ length: 5 }).map((_, index) => (
          <span key={index} className={styles.timelineDotEmpty} />
        ))}
      </div>
    );
  }

  const padded = [...Array(Math.max(0, 5 - runs.length)).fill(null), ...runs].slice(-5);
  return (
    <div className={styles.timeline}>
      {padded.map((run, index) => {
        if (!run) return <span key={index} className={styles.timelineDotEmpty} title="기록 없음" />;
        const success = run.status === 'success';
        return (
          <span
            key={index}
            className={success ? styles.timelineDotSuccess : styles.timelineDotFail}
            title={`${success ? '성공' : '실패'}${run.duration ? ` (${run.duration.toFixed(1)}초)` : ''}`}
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
  const crawlerFilter = useAdminStore((state) => state.crawlerFilter);
  const setCrawlerFilter = useAdminStore((state) => state.setCrawlerFilter);
  const getFilteredCrawlers = useAdminStore((state) => state.getFilteredCrawlers);
  const fetchCrawlers = useAdminStore((state) => state.fetchCrawlers);
  const runCrawler = useAdminStore((state) => state.runCrawler);
  const loading = useAdminStore((state) => state.crawlersLoading);
  const error = useAdminStore((state) => state.crawlersError);
  const filtered = getFilteredCrawlers();

  const [runStates, setRunStates] = useState({});
  const [checkedIds, setCheckedIds] = useState(new Set());
  const [collapsedGroups, setCollapsedGroups] = useState(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [clockTick, setClockTick] = useState(() => Date.now());
  const [lotteCategories, setLotteCategories] = useState([]);
  const [lotteCategoryLoading, setLotteCategoryLoading] = useState(false);
  const pollRefs = useRef({});

  useEffect(() => {
    fetchCrawlers();
  }, [fetchCrawlers]);

  useEffect(() => {
    const hasRunning = Object.values(runStates).some(
      (state) => state?.phase === 'running' || state?.phase === 'starting',
    );
    if (!hasRunning) return undefined;
    const timer = setInterval(() => setClockTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [runStates]);

  useEffect(() => () => {
    Object.values(pollRefs.current).forEach((timer) => clearTimeout(timer));
  }, []);

  const setRunState = useCallback((id, state) => {
    setRunStates((previous) => ({ ...previous, [id]: state }));
  }, []);

  const clearRunState = useCallback((id, delay = 8000) => {
    setTimeout(() => {
      setRunStates((previous) => {
        const next = { ...previous };
        delete next[id];
        return next;
      });
    }, delay);
  }, []);

  const startPolling = useCallback((id) => {
    if (pollRefs.current[id]) clearTimeout(pollRefs.current[id]);
    const startedAt = Date.now();

    const poll = async () => {
      try {
        const data = await api.getCrawlerStatus(id);
        if (SUCCESS_STATUSES.has(data.status)) {
          const partial = data.status === 'partial_failure';
          setRunState(id, {
            phase: 'done',
            success: !partial,
            message: `${partial ? '⚠️ 부분 완료' : '✅ 크롤링 완료'} — ${data.items_found ?? 0}건 발견, ${data.items_saved ?? 0}건 저장 (${(data.duration ?? 0).toFixed(1)}초)`,
            summary: buildCounterSummary(data, { id }),
          });
          delete pollRefs.current[id];
          await fetchCrawlers();
          clearRunState(id);
          return;
        }
        if (data.status === 'failed') {
          setRunState(id, {
            phase: 'done',
            success: false,
            message: `❌ 크롤링 실패: ${(data.errors || []).join(', ') || data.error || '알 수 없는 오류'}`,
            summary: buildCounterSummary(data, { id }),
          });
          delete pollRefs.current[id];
          await fetchCrawlers();
          clearRunState(id);
          return;
        }

        setRunState(id, {
          phase: 'running',
          success: true,
          startedAt,
          message: `⏳ 크롤링 실행 중...${data.progress_stage ? ` (${data.progress_stage})` : ''}`,
          summary: buildCounterSummary(data, { id }),
        });
      } catch {
        setRunState(id, {
          phase: 'running',
          success: false,
          startedAt,
          message: '⚠️ 상태 확인 연결이 불안정합니다. 다시 확인 중...',
        });
      }

      pollRefs.current[id] = setTimeout(poll, POLL_INTERVAL_MS);
    };

    pollRefs.current[id] = setTimeout(poll, POLL_INTERVAL_MS);
  }, [clearRunState, fetchCrawlers, setRunState]);

  const handleRun = useCallback(async (id) => {
    if (runStates[id]?.phase === 'running' || runStates[id]?.phase === 'starting') return;
    setRunState(id, {
      phase: 'starting',
      success: true,
      startedAt: Date.now(),
      message: '크롤러 실행 요청 중...',
    });
    const result = await runCrawler(id);
    if (!result) {
      setRunState(id, { phase: 'done', success: false, message: '❌ 실행 요청에 실패했습니다.' });
      clearRunState(id, 4000);
      return;
    }
    setRunState(id, {
      phase: 'running',
      success: true,
      startedAt: Date.now(),
      message: '⏳ 크롤링 실행 중...',
      summary: buildCounterSummary(result, { id }),
    });
    startPolling(id);
  }, [clearRunState, runCrawler, runStates, setRunState, startPolling]);

  const handleRetryWafBlocked = useCallback(async (crawler) => {
    const id = crawler.id;
    setRunState(id, { phase: 'starting', success: true, message: '🛡️ WAF 보류 카테고리 재시도 준비 중...' });
    try {
      const data = await api.retryWafBlocked(id);
      if (data.status === 'running') {
        setRunState(id, {
          phase: 'running',
          success: true,
          startedAt: Date.now(),
          message: `🛡️ WAF 보류 ${data.wafBlockedCount ?? 0}건 재시도 중...`,
        });
        startPolling(id);
      } else {
        setRunState(id, {
          phase: 'done',
          success: true,
          message: data.message || '재시도할 WAF 보류 카테고리가 없습니다.',
        });
        clearRunState(id, 5000);
      }
    } catch (err) {
      setRunState(id, {
        phase: 'done',
        success: false,
        message: `❌ WAF 재시도 실패: ${err?.message || '요청 실패'}`,
      });
      clearRunState(id, 5000);
    }
  }, [clearRunState, setRunState, startPolling]);

  const handleLoadLotteCategories = useCallback(async (refresh = false) => {
    setLotteCategoryLoading(true);
    try {
      const data = await api.getLotteCategories(refresh);
      setLotteCategories(Array.isArray(data.categories) ? data.categories : []);
    } catch (err) {
      setRunState('lottemart', {
        phase: 'done',
        success: false,
        message: `❌ 롯데 카테고리 목록 로드 실패: ${err?.message || '요청 실패'}`,
      });
      clearRunState('lottemart', 5000);
    } finally {
      setLotteCategoryLoading(false);
    }
  }, [clearRunState, setRunState]);

  const handleRunLotteCategory = useCallback(async (category) => {
    setRunState('lottemart', {
      phase: 'starting',
      success: true,
      message: `🧭 롯데 카테고리 실행 준비 중: ${category.query || category.category_hint || category.url}`,
    });
    try {
      const data = await api.runLotteCategory(category);
      if (data.status !== 'running') {
        setRunState('lottemart', {
          phase: 'done',
          success: false,
          message: data.message || '롯데 카테고리 실행을 시작하지 못했습니다.',
        });
        clearRunState('lottemart', 5000);
        return;
      }
      setRunState('lottemart', {
        phase: 'running',
        success: true,
        startedAt: Date.now(),
        message: data.message || '🧭 롯데 카테고리 실행 중...',
      });
      startPolling('lottemart');
    } catch (err) {
      setRunState('lottemart', {
        phase: 'done',
        success: false,
        message: `❌ 롯데 카테고리 실행 실패: ${err?.message || '요청 실패'}`,
      });
      clearRunState('lottemart', 5000);
    }
  }, [clearRunState, setRunState, startPolling]);

  const handleBulkRun = useCallback(async () => {
    if (checkedIds.size === 0) return;
    setBulkRunning(true);
    const ids = [...checkedIds];
    try {
      const response = await api.bulkRunCrawlers(ids);
      for (const result of response.results || []) {
        if (result.status === 'running') {
          setRunState(result.crawler_id, {
            phase: 'running',
            success: true,
            startedAt: Date.now(),
            message: '⏳ 크롤링 실행 중...',
          });
          startPolling(result.crawler_id);
        } else {
          setRunState(result.crawler_id, {
            phase: 'done',
            success: false,
            message: result.message || result.error || '실행 실패',
          });
          clearRunState(result.crawler_id, 4000);
        }
      }
    } catch {
      for (const id of ids) {
        setRunState(id, {
          phase: 'done',
          success: false,
          message: '벌크 실행에 실패했습니다. 잠시 후 다시 시도해 주세요.',
        });
        clearRunState(id, 4000);
      }
    } finally {
      setBulkRunning(false);
      setCheckedIds(new Set());
    }
  }, [checkedIds, clearRunState, setRunState, startPolling]);

  const toggleCheck = useCallback((id) => {
    setCheckedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAllInGroup = useCallback((ids) => {
    setCheckedIds((previous) => {
      const next = new Set(previous);
      const allChecked = ids.every((id) => next.has(id));
      if (allChecked) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }, []);

  const toggleCollapse = useCallback((category) => {
    setCollapsedGroups((previous) => {
      const next = new Set(previous);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }, []);

  const formatTime = (iso) => {
    if (!iso) return '-';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleString('ko-KR', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const grouped = useMemo(() => {
    if (crawlerFilter !== 'all') return null;
    const groups = {};
    for (const crawler of filtered) {
      const category = crawler.category || 'etc';
      if (!groups[category]) groups[category] = [];
      groups[category].push(crawler);
    }
    const order = ['mart', 'shopping', 'hotdeal', 'etc'];
    return order
      .filter((key) => groups[key])
      .map((key) => ({ key, label: CATEGORY_LABELS[key] || key, crawlers: groups[key] }));
  }, [crawlerFilter, filtered]);

  const renderCard = (crawler) => {
    const status = STATUS_MAP[crawler.status] || STATUS_MAP.active;
    const runState = runStates[crawler.id];
    const isRunning = runState?.phase === 'running' || runState?.phase === 'starting';
    const isChecked = checkedIds.has(crawler.id);
    const wafBlockedCount = Number(crawler.wafBlockedCount || 0);
    const wafBlockedItems = Array.isArray(crawler.wafBlockedItems) ? crawler.wafBlockedItems : [];
    const elapsedSec = isRunning && runState?.startedAt
      ? Math.max(1, Math.floor((clockTick - runState.startedAt) / 1000))
      : null;

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
              <span className={`${styles.statusDot} ${status.dot}`} />
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
            <span className={styles.metaLabel}>최근 실행</span>
            <MiniTimeline runs={crawler.recentRuns} />
          </div>
        </div>

        {runState && (
          <div className={`${styles.runResult} ${runState.success ? styles.runResultSuccess : styles.runResultFail}`}>
            <div className={styles.runStatusLine}>
              {isRunning && <Spinner />}
              <span>{runState.message}</span>
              {elapsedSec != null && <span className={styles.elapsedBadge}>{elapsedSec}초 경과</span>}
            </div>
            <CounterChips summary={runState.summary} />
          </div>
        )}

        {crawler.id === 'lottemart' && (
          <div className={styles.runResult} style={{ background: '#f8fafc', color: '#334155', borderColor: '#e2e8f0' }}>
            <div className={styles.runStatusLine}>
              <span>🛡️ WAF 보류 {wafBlockedCount.toLocaleString()}건</span>
              {wafBlockedCount === 0 && <span className={styles.elapsedBadge}>현재 보류 없음</span>}
            </div>
            {wafBlockedItems.length > 0 && (
              <div style={{ display: 'grid', gap: 4, marginTop: 6, fontSize: 12 }}>
                {wafBlockedItems.slice(0, 3).map((item) => (
                  <span key={item.url || item.query}>
                    실패: {Array.isArray(item.category_path) && item.category_path.length > 0
                      ? item.category_path.join(' > ')
                      : (item.query || item.category_hint || item.url)}
                    {item.status_code ? ` (HTTP ${item.status_code})` : ''}
                  </span>
                ))}
              </div>
            )}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
              <button
                className={styles.actionBtn}
                onClick={() => handleLoadLotteCategories(false)}
                disabled={lotteCategoryLoading || isRunning}
              >
                {lotteCategoryLoading ? <Spinner /> : <ChevronDown size={14} />}
                카테고리 목록
              </button>
              <button
                className={styles.actionBtn}
                onClick={() => handleLoadLotteCategories(true)}
                disabled={lotteCategoryLoading || isRunning}
              >
                새로고침
              </button>
              {lotteCategories.slice(0, 8).map((category) => (
                <button
                  key={category.key || category.url}
                  className={styles.actionBtn}
                  title={category.url}
                  onClick={() => handleRunLotteCategory(category)}
                  disabled={isRunning}
                >
                  {category.category_hint || category.query}
                </button>
              ))}
            </div>
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
          {crawler.id === 'lottemart' && (
            <button
              className={styles.actionBtn}
              title={wafBlockedCount > 0 ? 'WAF로 보류된 롯데마트 카테고리만 재시도' : '현재 WAF 보류 카테고리가 없습니다'}
              onClick={() => handleRetryWafBlocked(crawler)}
              disabled={isRunning || wafBlockedCount === 0}
              style={{ marginLeft: 'auto', background: '#fffbeb', color: '#b45309', borderColor: '#fde68a' }}
            >
              <RotateCcw size={14} />
              WAF 재시도 ({wafBlockedCount})
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
            <button className={styles.bulkRunBtn} onClick={handleBulkRun} disabled={bulkRunning}>
              {bulkRunning ? <Spinner /> : <Play size={16} />}
              선택 실행 ({checkedIds.size})
            </button>
          )}
        </div>
      </div>

      {error && <div className={styles.errorBanner}>⚠️ {error}</div>}

      <div className={styles.filters}>
        {CATEGORIES.map((category) => (
          <button
            key={category.key}
            className={crawlerFilter === category.key ? styles.filterBtnActive : styles.filterBtn}
            onClick={() => setCrawlerFilter(category.key)}
          >
            {category.label}
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
          {error ? '크롤러 목록을 불러올 수 없습니다.' : '등록된 크롤러가 없습니다.'}
        </div>
      )}

      {grouped && grouped.map((group) => {
        const collapsed = collapsedGroups.has(group.key);
        const groupIds = group.crawlers.map((crawler) => crawler.id);
        const allChecked = groupIds.length > 0 && groupIds.every((id) => checkedIds.has(id));
        return (
          <div key={group.key} className={styles.group}>
            <div className={styles.groupHeader}>
              <button className={styles.groupToggle} onClick={() => toggleCollapse(group.key)}>
                {collapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
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
            {!collapsed && <div className={styles.grid}>{group.crawlers.map(renderCard)}</div>}
          </div>
        );
      })}

      {!grouped && <div className={styles.grid}>{filtered.map(renderCard)}</div>}
    </div>
  );
}
