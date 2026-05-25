/**
 * WeeklyAlertsPage.jsx
 * 주간 알림 — 사라진 SKU 목록 조회 및 해결 처리.
 * GET  /api/weekly/alerts?status=open|resolved|all&mart=...
 * POST /api/weekly/alerts/{id}/resolve
 */
import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, Filter } from 'lucide-react';
import styles from './WeeklyAlertsPage.module.css';

const MART_OPTIONS = [
  { value: '', label: '전체 마트' },
  { value: 'emart', label: 'E마트' },
  { value: 'homeplus', label: '홈플러스' },
  { value: 'lottemart', label: '롯데마트' },
  { value: 'costco', label: '코스트코' },
];

const STATUS_OPTIONS = [
  { value: 'open', label: '미해결' },
  { value: 'resolved', label: '해결됨' },
  { value: 'all', label: '전체' },
];

function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch { return iso; }
}

function formatPrice(p) {
  if (p == null) return '—';
  return Number(p).toLocaleString('ko-KR') + '원';
}

function StatusBadge({ status }) {
  return (
    <span className={`${styles.badge} ${status === 'resolved' ? styles.badgeResolved : styles.badgeOpen}`}>
      {status === 'resolved' ? '해결됨' : '미해결'}
    </span>
  );
}

export default function WeeklyAlertsPage() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('open');
  const [mart, setMart] = useState('');
  const [resolving, setResolving] = useState(null); // alert id being resolved

  const fetch_ = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ status, limit: '200' });
      if (mart) params.set('mart', mart);
      const res = await fetch(`/api/weekly/alerts?${params}`, { cache: 'no-store' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setAlerts(Array.isArray(data) ? data : data.items || []);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [status, mart]);

  useEffect(() => { fetch_(); }, [fetch_]);

  const handleResolve = useCallback(async (id) => {
    if (!window.confirm('이 알림을 해결됨으로 표시하시겠습니까?')) return;
    setResolving(id);
    try {
      const res = await fetch(`/api/weekly/alerts/${id}/resolve`, { method: 'POST', cache: 'no-store' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      // 목록에서 즉시 반영
      setAlerts((prev) => prev.map((a) => a.id === id ? { ...a, status: 'resolved', resolved_at: new Date().toISOString() } : a));
    } catch (e) {
      alert(`해결 처리 실패: ${e.message}`);
    } finally {
      setResolving(null);
    }
  }, []);

  const openCount = alerts.filter((a) => a.status === 'open').length;

  return (
    <div className={styles.page}>
      {/* 헤더 */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>
            <AlertTriangle size={20} className={styles.titleIcon} />
            주간 알림 — 사라진 SKU
          </h1>
          <p className={styles.desc}>
            지난 주 대비 사라진 SKU를 감지한 알림 목록입니다.
            운영자가 확인 후 '해결됨'으로 표시하세요.
          </p>
        </div>
        <button
          className={styles.refreshBtn}
          onClick={fetch_}
          disabled={loading}
          title="새로고침"
        >
          <RefreshCw size={16} className={loading ? styles.spinning : ''} />
          새로고침
        </button>
      </div>

      {/* 필터 바 */}
      <div className={styles.filterBar}>
        <Filter size={15} className={styles.filterIcon} />
        <span className={styles.filterLabel}>필터:</span>
        <div className={styles.filterGroup}>
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              className={`${styles.filterBtn} ${status === opt.value ? styles.filterBtnActive : ''}`}
              onClick={() => setStatus(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <select
          className={styles.martSelect}
          value={mart}
          onChange={(e) => setMart(e.target.value)}
        >
          {MART_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* 요약 배너 */}
      {!loading && status !== 'resolved' && openCount > 0 && (
        <div className={styles.summaryBanner}>
          <AlertTriangle size={16} />
          <span>미해결 알림 <strong>{openCount}건</strong>이 있습니다. 각 항목을 확인 후 해결 처리하세요.</span>
        </div>
      )}
      {!loading && alerts.length === 0 && !error && (
        <div className={styles.empty}>
          <CheckCircle2 size={28} />
          <p>해당 조건의 알림이 없습니다.</p>
        </div>
      )}

      {error && (
        <div className={styles.errorBox}>
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {/* 알림 목록 */}
      {alerts.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>마트</th>
                <th>상품명</th>
                <th>마지막 가격</th>
                <th>마지막 캡처</th>
                <th>감지 일시</th>
                <th>상태</th>
                <th>액션</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id} className={a.status === 'resolved' ? styles.rowResolved : ''}>
                  <td><span className={styles.martChip}>{a.mart}</span></td>
                  <td className={styles.titleCell} title={a.last_seen_title}>{a.last_seen_title || '—'}</td>
                  <td className={styles.priceCell}>{formatPrice(a.last_seen_price)}</td>
                  <td className={styles.dateCell}>{formatDate(a.last_captured_at)}</td>
                  <td className={styles.dateCell}>{formatDate(a.detected_at)}</td>
                  <td><StatusBadge status={a.status} /></td>
                  <td>
                    {a.status === 'open' ? (
                      <button
                        className={styles.resolveBtn}
                        onClick={() => handleResolve(a.id)}
                        disabled={resolving === a.id}
                      >
                        {resolving === a.id ? '처리 중…' : '해결'}
                      </button>
                    ) : (
                      <span className={styles.resolvedAt}>{formatDate(a.resolved_at)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
