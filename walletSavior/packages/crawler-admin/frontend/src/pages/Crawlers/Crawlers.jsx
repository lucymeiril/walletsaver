import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import useAdminStore from '../../stores/adminStore';
import { api } from '../../api/client';
import { Play, Settings, Plus, Power, X, CheckSquare, Square, Loader, ChevronDown, ChevronRight } from 'lucide-react';
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
const POLL_INTERVAL = 2000;
const MAX_POLLS = Math.ceil(TIMEOUT_SEC / (POLL_INTERVAL / 1000));

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

function MiniTimeline({ runs }) {
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
}

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
  const loading = useAdminStore((s) => s.loading);
  const error = useAdminStore((s) => s.error);
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
  const pollRefs = useRef({});

  useEffect(() => {
    fetchCrawlers();
  }, [fetchCrawlers]);

  useEffect(() => {
    return () => {
      Object.values(pollRefs.current).forEach(clearInterval);
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
    let pollCount = 0;
    const startTime = Date.now();
    if (pollRefs.current[id]) clearInterval(pollRefs.current[id]);

    pollRefs.current[id] = setInterval(async () => {
      pollCount++;
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
      try {
        const resp = await fetch(`/api/crawlers/${id}/status`);
        if (resp.ok) {
          const data = await resp.json();
          if (data.status === 'success') {
            setRunState(id, {
              phase: 'done',
              success: true,
              message: `✅ 크롤링 완료 — ${data.items_found ?? 0}건 발견, ${data.items_saved ?? 0}건 저장 (${(data.duration ?? 0).toFixed(1)}초)`,
            });
            clearInterval(pollRefs.current[id]);
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
            clearInterval(pollRefs.current[id]);
            delete pollRefs.current[id];
            clearRunState(id);
            return;
          }
        }
      } catch { /* 폴링 실패 무시 */ }

      setRunState(id, {
        phase: 'running',
        success: true,
        message: `⏳ 크롤링 실행 중... (${elapsed}초 경과)`,
      });

      if (pollCount >= MAX_POLLS) {
        clearInterval(pollRefs.current[id]);
        delete pollRefs.current[id];
        setRunState(id, {
          phase: 'done',
          success: false,
          message: `⏱ ${TIMEOUT_SEC}초 초과 — 타임아웃`,
        });
        clearRunState(id, 6000);
      }
    }, POLL_INTERVAL);
  }, [setRunState, clearRunState, fetchCrawlers]);

  const handleRun = useCallback(async (id) => {
    setRunState(id, { phase: 'starting', success: true, message: '크롤러 실행 요청 중...' });
    const result = await runCrawler(id);
    if (result) {
      setRunState(id, { phase: 'running', success: true, message: '⏳ 크롤링 실행 중... (0초 경과)' });
      startPolling(id);
    } else {
      setRunState(id, { phase: 'done', success: false, message: '크롤러 실행 요청 실패' });
      clearRunState(id, 4000);
    }
  }, [runCrawler, setRunState, startPolling, clearRunState]);

  const handleBulkRun = useCallback(async () => {
    if (checkedIds.size === 0) return;
    setBulkRunning(true);
    const ids = [...checkedIds];
    try {
      const resp = await api.bulkRunCrawlers(ids);
      const results = resp.results || [];
      for (const r of results) {
        if (r.status === 'running') {
          setRunState(r.crawler_id, { phase: 'running', success: true, message: '⏳ 크롤링 실행 중... (0초 경과)' });
          startPolling(r.crawler_id);
        } else {
          setRunState(r.crawler_id, { phase: 'done', success: false, message: r.message || r.error || '실행 실패' });
          clearRunState(r.crawler_id, 4000);
        }
      }
    } catch (err) {
      for (const id of ids) {
        setRunState(id, { phase: 'done', success: false, message: `벌크 실행 실패: ${err.message}` });
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
    } catch (err) {
      alert(`설정 저장 실패: ${err.message}`);
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
            {isRunning && <Spinner />}
            <span>{rs.message}</span>
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
        <div className={styles.errorBanner}>{error}</div>
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

      {filtered.length === 0 && !loading && (
        <div className={styles.emptyState}>등록된 크롤러가 없습니다</div>
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
