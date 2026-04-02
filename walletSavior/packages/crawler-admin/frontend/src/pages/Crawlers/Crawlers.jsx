import { useState, useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { api } from '../../api/client';
import { Play, Settings, Plus, Power, X } from 'lucide-react';
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

const STATUS_MAP = {
  active: { dot: styles.statusActive, label: '활성' },
  error: { dot: styles.statusError, label: '에러' },
  inactive: { dot: styles.statusInactive, label: '비활성' },
};

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

  const [runResult, setRunResult] = useState(null);
  const [settingsModal, setSettingsModal] = useState(null);
  const [settingsData, setSettingsData] = useState({ target_url: '', delay: 1, max_items: 100 });
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [showAddInfo, setShowAddInfo] = useState(false);

  useEffect(() => {
    fetchCrawlers();
  }, [fetchCrawlers]);

  const handleRun = async (id) => {
    setRunResult({ id, success: true, message: '크롤러 실행 요청 중...' });
    const result = await runCrawler(id);
    if (result) {
      setRunResult({ id, success: true, message: result.message || '크롤러 실행 시작됨 — 상태 추적 중...' });
      let pollCount = 0;
      const poll = setInterval(async () => {
        pollCount++;
        try {
          const statusResp = await fetch(`/api/crawlers/${id}/status`);
          if (statusResp.ok) {
            const statusData = await statusResp.json();
            if (statusData.status === 'success') {
              setRunResult({
                id,
                success: true,
                message: `✅ 크롤링 완료 — ${statusData.items_found ?? 0}건 발견, ${statusData.items_saved ?? 0}건 저장 (${(statusData.duration ?? 0).toFixed(1)}초)`,
              });
              clearInterval(poll);
              fetchCrawlers();
              setTimeout(() => setRunResult(null), 8000);
            } else if (statusData.status === 'failed') {
              setRunResult({
                id,
                success: false,
                message: `❌ 크롤링 실패: ${(statusData.errors || []).join(', ') || '알 수 없는 오류'}`,
              });
              clearInterval(poll);
              setTimeout(() => setRunResult(null), 8000);
            }
          }
        } catch { /* 폴링 실패 무시 */ }
        if (pollCount >= 60) {
          clearInterval(poll);
          setRunResult({ id, success: false, message: '⏱ 시간 초과 — 크롤러 상태를 확인해주세요' });
          setTimeout(() => setRunResult(null), 6000);
        }
      }, 2000);
    } else {
      setRunResult({ id, success: false, message: '크롤러 실행 요청 실패' });
      setTimeout(() => setRunResult(null), 4000);
    }
  };

  const openSettings = async (crawlerId) => {
    setSettingsModal(crawlerId);
    setSettingsLoading(true);
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
    setSettingsLoading(true);
    try {
      await api.updateCrawlerSettings(settingsModal, settingsData);
      setSettingsModal(null);
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

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.pageTitle}>크롤러 관리</h1>
        <div className={styles.actions}>
          <button className={styles.addBtn} onClick={() => setShowAddInfo(true)}>
            <Plus size={16} />
            크롤러 추가
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          padding: '12px 16px', borderRadius: '8px', marginBottom: '16px',
          background: 'rgba(248,113,113,0.15)', color: 'var(--red)',
          fontSize: 'var(--fs-sm)',
        }}>
          {error}
        </div>
      )}

      <div className={styles.filters}>
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            className={
              crawlerFilter === cat.key
                ? styles.filterBtnActive
                : styles.filterBtn
            }
            onClick={() => setCrawlerFilter(cat.key)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      <div className={styles.grid}>
        {runResult && (
          <div key="run-result" style={{
            gridColumn: '1 / -1',
            padding: '12px 16px',
            borderRadius: '8px',
            background: runResult.success ? 'rgba(52,211,153,0.15)' : 'rgba(248,113,113,0.15)',
            color: runResult.success ? 'var(--green)' : 'var(--red)',
            fontSize: 'var(--fs-sm)',
            fontWeight: 'var(--fw-medium)',
          }}>
            {runResult.message}
          </div>
        )}
        {filtered.length === 0 && !loading && (
          <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '40px', color: 'var(--text3)' }}>
            등록된 크롤러가 없습니다
          </div>
        )}
        {filtered.map((crawler) => {
          const st = STATUS_MAP[crawler.status] || STATUS_MAP.inactive;
          return (
            <div key={crawler.id} className={styles.card}>
              <div className={styles.cardHeader}>
                <div className={styles.cardTitle}>
                  <span className={`${styles.statusDot} ${st.dot}`} />
                  {crawler.name}
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
                  <span className={styles.metaValue}>
                    {formatTime(crawler.lastCrawl)}
                  </span>
                </div>
                <div className={styles.metaRow}>
                  <span className={styles.metaLabel}>성공률</span>
                  <span className={styles.metaValue}>
                    {crawler.successRate}%
                  </span>
                </div>
                <div className={styles.metaRow}>
                  <span className={styles.metaLabel}>총 실행 횟수</span>
                  <span className={styles.metaValue}>
                    {(crawler.totalRuns || 0).toLocaleString()}회
                  </span>
                </div>
              </div>

              <div className={styles.cardActions}>
                <button
                  className={styles.actionBtn}
                  title="수동 실행"
                  onClick={() => handleRun(crawler.id)}
                  disabled={loading}
                >
                  <Play size={14} />
                  {loading && runResult?.id === crawler.id ? '실행중...' : '실행'}
                </button>
                <button className={styles.actionBtn} title="설정" onClick={() => openSettings(crawler.id)}>
                  <Settings size={14} />
                  설정
                </button>
                <button
                  className={
                    crawler.status === 'active'
                      ? styles.toggleBtnActive
                      : styles.toggleBtn
                  }
                  onClick={() => toggleCrawlerStatus(crawler.id)}
                  title={
                    crawler.status === 'active' ? '비활성화' : '활성화'
                  }
                >
                  <Power size={14} />
                  {crawler.status === 'active' ? '활성' : '비활성'}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Settings Modal */}
      {settingsModal && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}
          onClick={(e) => e.target === e.currentTarget && setSettingsModal(null)}
        >
          <div style={{
            background: 'var(--bg2)', borderRadius: '12px', padding: '24px',
            width: '100%', maxWidth: '420px', color: 'var(--text1)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3 style={{ margin: 0 }}>크롤러 설정 — {settingsModal}</h3>
              <button onClick={() => setSettingsModal(null)} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer' }}>
                <X size={20} />
              </button>
            </div>

            {settingsLoading ? (
              <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text3)' }}>로딩 중...</div>
            ) : (
              <>
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px', color: 'var(--text2)' }}>대상 URL</label>
                  <input
                    type="text"
                    value={settingsData.target_url}
                    onChange={(e) => setSettingsData({ ...settingsData, target_url: e.target.value })}
                    style={{
                      width: '100%', padding: '8px 12px', borderRadius: '6px',
                      background: 'var(--bg3)', border: '1px solid var(--border)', color: 'var(--text1)',
                      fontSize: '14px', boxSizing: 'border-box',
                    }}
                  />
                </div>
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px', color: 'var(--text2)' }}>요청 딜레이 (초)</label>
                  <input
                    type="number"
                    min="0"
                    step="0.5"
                    value={settingsData.delay}
                    onChange={(e) => setSettingsData({ ...settingsData, delay: parseFloat(e.target.value) || 0 })}
                    style={{
                      width: '100%', padding: '8px 12px', borderRadius: '6px',
                      background: 'var(--bg3)', border: '1px solid var(--border)', color: 'var(--text1)',
                      fontSize: '14px', boxSizing: 'border-box',
                    }}
                  />
                </div>
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px', color: 'var(--text2)' }}>최대 수집 항목 수</label>
                  <input
                    type="number"
                    min="1"
                    value={settingsData.max_items}
                    onChange={(e) => setSettingsData({ ...settingsData, max_items: parseInt(e.target.value) || 100 })}
                    style={{
                      width: '100%', padding: '8px 12px', borderRadius: '6px',
                      background: 'var(--bg3)', border: '1px solid var(--border)', color: 'var(--text1)',
                      fontSize: '14px', boxSizing: 'border-box',
                    }}
                  />
                </div>
                <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                  <button
                    onClick={() => setSettingsModal(null)}
                    style={{
                      padding: '8px 16px', borderRadius: '6px', border: '1px solid var(--border)',
                      background: 'transparent', color: 'var(--text2)', cursor: 'pointer',
                    }}
                  >
                    취소
                  </button>
                  <button
                    onClick={saveSettings}
                    disabled={settingsLoading}
                    style={{
                      padding: '8px 16px', borderRadius: '6px', border: 'none',
                      background: 'var(--accent)', color: '#fff', cursor: 'pointer',
                    }}
                  >
                    저장
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Add Crawler Info Modal */}
      {showAddInfo && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}
          onClick={(e) => e.target === e.currentTarget && setShowAddInfo(false)}
        >
          <div style={{
            background: 'var(--bg2)', borderRadius: '12px', padding: '24px',
            width: '100%', maxWidth: '500px', color: 'var(--text1)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0 }}>크롤러 추가 방법</h3>
              <button onClick={() => setShowAddInfo(false)} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer' }}>
                <X size={20} />
              </button>
            </div>
            <div style={{ fontSize: '14px', lineHeight: '1.7', color: 'var(--text2)' }}>
              <p>새 크롤러를 추가하려면 <code style={{ background: 'var(--bg3)', padding: '2px 6px', borderRadius: '4px' }}>plugin.yaml</code> 파일을 생성하세요:</p>
              <ol style={{ paddingLeft: '20px' }}>
                <li><code>crawlers/[카테고리]/[크롤러명]/</code> 디렉토리 생성</li>
                <li><code>plugin.yaml</code> 파일 작성 (이름, 버전, 대상 URL 등)</li>
                <li><code>crawler.py</code> 파일에 CrawlerContract 구현</li>
                <li>서버 재시작 시 자동 등록됨</li>
              </ol>
              <div style={{
                background: 'var(--bg3)', borderRadius: '8px', padding: '12px',
                fontFamily: 'monospace', fontSize: '12px', marginTop: '12px',
                whiteSpace: 'pre',
              }}>
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
              </div>
            </div>
            <div style={{ marginTop: '16px', textAlign: 'right' }}>
              <button
                onClick={() => setShowAddInfo(false)}
                style={{
                  padding: '8px 16px', borderRadius: '6px', border: 'none',
                  background: 'var(--accent)', color: '#fff', cursor: 'pointer',
                }}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
