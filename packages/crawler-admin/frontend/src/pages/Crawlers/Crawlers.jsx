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
const TERMINAL_STATUSES = new Set(['success', 'partial', 'partial_failure', 'failed', 'cancelled']);

const firstCount = (...values) => values.find(value => typeof value === 'number' && Number.isInteger(value) && value >= 0) ?? null;
const countText = value => value == null ? '미확인' : `${value.toLocaleString()}건`;

function runDiagnostics(data) {
  const quality = data.quality_details || {};
  return [...new Set([
    ...(Array.isArray(data.errors) ? data.errors : []), data.error,
    quality.zero_result_diagnostic?.message,
    ...(Array.isArray(quality.operator_diagnostics) ? quality.operator_diagnostics.map(item => item.message) : []),
  ].filter(value => typeof value === 'string' && value.trim()))];
}

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
    : firstCount(data.error_count, quality.error_count);
  const found = firstCount(data.total_collected, data.items_found, data.items_count,
    data.source_raw_count, quality.source_raw_count, data.total);
  const valid = firstCount(data.items_valid, data.valid_items);
  const saved = firstCount(data.items_saved, data.saved_items);
  const duplicates = firstCount(data.duplicates, data.duplicate_count, data.deduplicated_count, quality.deduplicated_count);

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
          {name} {value == null ? '미확인' : value.toLocaleString()}
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
            title={`${run.status === 'partial' || run.status === 'partial_failure' ? '부분 완료' : success ? '서버 기록: 성공' : run.status === 'failed' ? '실패' : '상태 미확인'}${run.duration ? ` (${run.duration.toFixed(1)}초)` : ''}`}
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
  const [emartCategories, setEmartCategories] = useState([]);
  const [selectedEmartCategoryId, setSelectedEmartCategoryId] = useState('');
  const [emartCategoryLoading, setEmartCategoryLoading] = useState(false);
  const [lotteCategories, setLotteCategories] = useState([]);
  const [lotteCategoryLoading, setLotteCategoryLoading] = useState(false);
  const [lotteSourceUrl, setLotteSourceUrl] = useState('');
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
        if (TERMINAL_STATUSES.has(data.status)) {
          const partial = data.status === 'partial' || data.status === 'partial_failure';
          const summary = buildCounterSummary(data, { id });
          const completed = data.status === 'success' && summary.total > 0 && summary.valid > 0 && summary.saved > 0;
          const label = partial ? '⚠️ 부분 완료' : data.status === 'failed' ? '❌ 수집·저장 실패'
            : data.status === 'cancelled' ? '실행 취소' : completed ? '✅ 수집·저장 단계 완료' : '⚠️ 완료 확인 미충족';
          setRunState(id, {
            phase: 'done',
            success: completed,
            message: `${label} — 발견 ${countText(summary.total)}, 유효 ${countText(summary.valid)}, 저장 ${countText(summary.saved)} (${typeof data.duration === 'number' && Number.isFinite(data.duration) && data.duration >= 0 ? `${data.duration.toFixed(1)}초` : '소요 시간 미확인'})`,
            summary,
            serverStatus: data.status,
            diagnostics: runDiagnostics(data),
            deliveryTarget: data.quality_details?.delivery?.target,
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

  const handleRun = useCallback(async (id, options) => {
    if (runStates[id]?.phase === 'running' || runStates[id]?.phase === 'starting') return;
    setRunState(id, {
      phase: 'starting',
      success: true,
      startedAt: Date.now(),
      message: '크롤러 실행 요청 중...',
    });
    const result = options ? await runCrawler(id, options) : await runCrawler(id);
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

  const handleLoadEmartCategories = useCallback(async () => {
    setEmartCategoryLoading(true);
    try {
      const data = await api.getEmartCategories();
      const categories = Array.isArray(data.categories) ? data.categories : [];
      setEmartCategories(categories);
      setSelectedEmartCategoryId((current) => (
        categories.some((category) => category.category_id === current)
          ? current
          : (categories[0]?.category_id || '')
      ));
    } catch (err) {
      setRunState('emart', {
        phase: 'done',
        success: false,
        message: `❌ 이마트 카테고리 목록 로드 실패: ${err?.message || '요청 실패'}`,
      });
      clearRunState('emart', 5000);
    } finally {
      setEmartCategoryLoading(false);
    }
  }, [clearRunState, setRunState]);

  const handleRunEmartCategory = useCallback(async () => {
    const category = emartCategories.find(
      (item) => item.category_id === selectedEmartCategoryId,
    );
    if (!category) return;
    setRunState('emart', {
      phase: 'starting',
      success: true,
      message: `🧭 이마트 카테고리 실행 준비 중: ${category.category_hint || category.query}`,
    });
    try {
      const data = await api.runEmartCategory(category);
      if (data.status !== 'running') {
        setRunState('emart', {
          phase: 'done',
          success: false,
          message: data.message || '이마트 카테고리 실행을 시작하지 못했습니다.',
        });
        clearRunState('emart', 5000);
        return;
      }
      setRunState('emart', {
        phase: 'running',
        success: true,
        startedAt: Date.now(),
        message: data.message || '🧭 이마트 카테고리 실행 중...',
      });
      startPolling('emart');
    } catch (err) {
      setRunState('emart', {
        phase: 'done',
        success: false,
        message: `❌ 이마트 카테고리 실행 실패: ${err?.message || '요청 실패'}`,
      });
      clearRunState('emart', 5000);
    }
  }, [clearRunState, emartCategories, selectedEmartCategoryId, setRunState, startPolling]);

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
            {runState.serverStatus && <p>서버 실행 상태: {runState.serverStatus} · 저장 수는 승인·공개 업데이트 수를 뜻하지 않습니다.</p>}
            {runState.deliveryTarget === 'pending_review' && <p>저장 대상: 검토 대기 접수 · 승인·공개 반영 미확인</p>}
            {runState.diagnostics?.length > 0 && <ul aria-label="실행 진단">{runState.diagnostics.map((message, index) => <li key={index}>{message}</li>)}</ul>}
          </div>
        )}

        {crawler.id === 'emart' && (
          <div className={styles.runResult} style={{ background: '#f8fafc', color: '#334155', borderColor: '#e2e8f0' }}>
            <div className={styles.runStatusLine}>
              <span>🧭 등록 카테고리 {emartCategories.length.toLocaleString()}개</span>
              <span className={styles.elapsedBadge}>한 번에 하나씩 저빈도 실행</span>
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
              <button
                className={styles.actionBtn}
                onClick={handleLoadEmartCategories}
                disabled={emartCategoryLoading || isRunning}
              >
                {emartCategoryLoading ? <Spinner /> : <ChevronDown size={14} />}
                카테고리 목록
              </button>
              {emartCategories.length > 0 && (
                <>
                  <select
                    aria-label="이마트 카테고리 선택"
                    value={selectedEmartCategoryId}
                    onChange={(event) => setSelectedEmartCategoryId(event.target.value)}
                    disabled={isRunning}
                  >
                    {emartCategories.map((category) => (
                      <option key={category.category_id} value={category.category_id}>
                        {category.category_hint || category.query || category.category_id}
                      </option>
                    ))}
                  </select>
                  <button
                    className={styles.actionBtn}
                    onClick={handleRunEmartCategory}
                    disabled={isRunning || !selectedEmartCategoryId}
                  >
                    <Play size={14} />
                    선택 카테고리 실행
                  </button>
                </>
              )}
            </div>
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

        {crawler.id === 'lottemart' && (
          <div style={{ marginTop: 8 }}>
            <label htmlFor="lotte-source-url">롯데마트 상품 URL · 한 상품 수집</label>
            <input id="lotte-source-url" type="url" value={lotteSourceUrl}
              onChange={(event) => setLotteSourceUrl(event.target.value)} disabled={isRunning}
              placeholder="https://lottemartzetta.com/products/OS.../details"
              style={{ width: '100%', marginTop: 4 }} />
            <button className={styles.actionBtn} disabled={isRunning || !/^https:\/\/lottemartzetta\.com\/products\/OS[0-9]{13}\/details\/?$/.test(lotteSourceUrl.trim())}
              onClick={() => handleRun(crawler.id, { source_url: lotteSourceUrl.trim() })}>
              상품 URL 한 번 수집
            </button>
            <small>한 상품만 요청합니다. 접근 제한이나 미확인 응답은 재요청하지 않습니다. 저장은 검토 대기 접수이며 승인·공개 반영과 다릅니다.</small>
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
