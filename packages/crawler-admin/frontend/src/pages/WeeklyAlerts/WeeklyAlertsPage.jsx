/**
 * Weekly alerts — disappeared SKU review and resolution.
 */
import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, Filter } from 'lucide-react';
import { getApiKey } from '../../stores/authStore';
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

function authHeaders() {
  const key = getApiKey();
  return key ? { 'X-API-Key': key } : {};
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch {
    return iso;
  }
}

function formatPrice(price) {
  if (price == null) return '—';
  return Number(price).toLocaleString('ko-KR') + '원';
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
  const [resolving, setResolving] = useState(null);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ status, limit: '200' });
      if (mart) params.set('mart', mart);
      const response = await fetch(`/api/weekly/alerts?${params}`, {
        cache: 'no-store',
        headers: authHeaders(),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
      const data = await response.json();
      setAlerts(Array.isArray(data) ? data : data.items || []);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }, [status, mart]);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  const handleResolve = useCallback(async (id) => {
    if (!window.confirm('이 알림을 해결됨으로 표시하시겠습니까?')) return;
    setResolving(id);
    try {
      const response = await fetch(`/api/weekly/alerts/${id}/resolve`, {
        method: 'POST',
        cache: 'no-store',
        headers: authHeaders(),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
      setAlerts((prev) => prev.map((alert) => (
        alert.id === id
          ? { ...alert, status: 'resolved', resolved_at: new Date().toISOString() }
          : alert
      )));
    } catch (err) {
      window.alert(`해결 처리 실패: ${err.message}`);
    } finally {
      setResolving(null);
    }
  }, []);

  const openCount = alerts.filter((alert) => alert.status === 'open').length;

  return (
    <div className={styles.page}>
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
          onClick={fetchAlerts}
          disabled={loading}
          title="새로고침"
        >
          <RefreshCw size={16} className={loading ? styles.spinning : ''} />
          새로고침
        </button>
      </div>

      <div className={styles.filterBar}>
        <Filter size={15} className={styles.filterIcon} />
        <span className={styles.filterLabel}>필터:</span>
        <div className={styles.filterGroup}>
          {STATUS_OPTIONS.map((option) => (
            <button
              key={option.value}
              className={`${styles.filterBtn} ${status === option.value ? styles.filterBtnActive : ''}`}
              onClick={() => setStatus(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <select
          className={styles.martSelect}
          value={mart}
          onChange={(event) => setMart(event.target.value)}
        >
          {MART_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>

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
              {alerts.map((alert) => (
                <tr key={alert.id} className={alert.status === 'resolved' ? styles.rowResolved : ''}>
                  <td><span className={styles.martChip}>{alert.mart}</span></td>
                  <td className={styles.titleCell} title={alert.last_seen_title}>{alert.last_seen_title || '—'}</td>
                  <td className={styles.priceCell}>{formatPrice(alert.last_seen_price)}</td>
                  <td className={styles.dateCell}>{formatDate(alert.last_captured_at)}</td>
                  <td className={styles.dateCell}>{formatDate(alert.detected_at)}</td>
                  <td><StatusBadge status={alert.status} /></td>
                  <td>
                    {alert.status === 'open' ? (
                      <button
                        className={styles.resolveBtn}
                        onClick={() => handleResolve(alert.id)}
                        disabled={resolving === alert.id}
                      >
                        {resolving === alert.id ? '처리 중…' : '해결'}
                      </button>
                    ) : (
                      <span className={styles.resolvedAt}>{formatDate(alert.resolved_at)}</span>
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
