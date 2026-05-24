/**
 * PendingEscalationPanel — pending_db_review 정체 건 escalation 큐 패널.
 *
 * 기능:
 *   - /api/escalation/pending 를 30초마다 폴링하여 정체 건 목록 표시
 *   - 각 건별 1-click 승인(approve) / 거부(reject) 버튼
 *   - 최근 1시간 정체 카운트 표시
 *   - 알람 임계 도달 시 빨간 카드 표시 (100건+ 또는 24시간+)
 *   - Rule A/B/C 배지로 자동 처리 가능 여부 시각화
 */
import { useCallback, useEffect, useState } from 'react';

const POLL_INTERVAL_MS = 30_000; // 30초 폴링

const RULE_BADGE = {
  auto_publish: { label: '자동발행 가능', cls: 'ok' },
  human_review: { label: '사람검토 필요', cls: 'warn' },
  alarm: { label: '알람 — 장기정체', cls: 'err' },
};

const GATE_LABEL = {
  gate_db_submitted: 'DB제출',
  gate_no_errors: '에러없음',
  gate_attempts_ok: '재시도OK',
  gate_not_stale: '시간OK',
};

function usePendingEscalation() {
  const [state, setState] = useState({ loading: true, error: null, data: null });
  const [lastRefresh, setLastRefresh] = useState(null);

  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fetch('/api/escalation/pending').then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      });
      setState({ loading: false, error: null, data });
      setLastRefresh(new Date());
    } catch (err) {
      setState((s) => ({ ...s, loading: false, error: err.message }));
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  return { ...state, refresh, lastRefresh };
}

async function requestJson(url, { method = 'POST', body } = {}) {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let parsed = null;
  try { parsed = text ? JSON.parse(text) : null; } catch { parsed = { raw: text }; }
  if (!res.ok) {
    const detail = parsed?.detail ?? `HTTP ${res.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return parsed;
}

function AlarmCard({ alarm }) {
  if (!alarm?.alarm_triggered) return null;
  return (
    <div style={{
      background: '#4a1010',
      border: '2px solid #f44',
      borderRadius: 6,
      padding: '12px 16px',
      marginBottom: 16,
      color: '#ffd',
    }}>
      <strong style={{ color: '#ff5555', fontSize: 16 }}>🚨 정체 알람</strong>
      <div style={{ marginTop: 4, fontSize: 13 }}>{alarm.alarm_reason}</div>
      <div style={{ marginTop: 4, fontSize: 12, color: '#cc9' }}>
        총 {alarm.total_pending}건 정체 · 최대 {alarm.max_stale_hours}시간 경과 ·
        임계: {alarm.thresholds?.stale_alarm_count}건 이상 또는 {alarm.thresholds?.stale_alarm_hours}시간 이상
      </div>
    </div>
  );
}

function GateBadges({ gates }) {
  if (!gates || gates.length === 0) return null;
  return (
    <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
      {gates.map((g) => (
        <span
          key={g.name}
          title={g.reason}
          style={{
            fontSize: 10,
            padding: '1px 5px',
            borderRadius: 3,
            background: g.passed ? '#1a3a1a' : '#3a1a1a',
            color: g.passed ? '#6c6' : '#f88',
            border: `1px solid ${g.passed ? '#4a4' : '#a44'}`,
            cursor: 'help',
          }}
        >
          {GATE_LABEL[g.name] ?? g.name} {g.passed ? '✓' : '✗'}
        </span>
      ))}
    </span>
  );
}

function EscalationRow({ item, onApprove, onReject, busy }) {
  const ruleBadge = RULE_BADGE[item.rule] ?? { label: item.rule, cls: '' };
  const hoursLabel = item.hours_stale != null
    ? `${item.hours_stale}시간 전`
    : '시간 미상';

  return (
    <tr style={{ borderBottom: '1px solid #333' }}>
      <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 12 }}>
        {item.raw_record_id}
      </td>
      <td style={{ padding: '6px 8px', fontSize: 12 }}>{item.source_name}</td>
      <td style={{ padding: '6px 8px', fontSize: 12, color: item.is_stale ? '#f88' : '#aaa' }}>
        {hoursLabel}
      </td>
      <td style={{ padding: '6px 8px', fontSize: 12 }}>
        {item.db_ingestion_id ?? <span style={{ color: '#888' }}>없음</span>}
      </td>
      <td style={{ padding: '6px 8px', fontSize: 12 }}>
        <span className={`badge ${ruleBadge.cls}`}>{ruleBadge.label}</span>
      </td>
      <td style={{ padding: '6px 8px' }}>
        <GateBadges gates={item.gates} />
      </td>
      <td style={{ padding: '6px 8px' }}>
        <span style={{ display: 'inline-flex', gap: 6 }}>
          <button
            style={{ fontSize: 11, padding: '2px 8px' }}
            disabled={busy}
            onClick={() => onApprove(item)}
            title="escalation 승인 — ai_safe_final_approve 또는 force 전환"
          >
            ✅ 승인
          </button>
          <button
            style={{ fontSize: 11, padding: '2px 8px', background: '#5a1a1a', borderColor: '#a33' }}
            disabled={busy}
            onClick={() => onReject(item)}
            title="escalation 거부 — rolled_back 처리"
          >
            ❌ 거부
          </button>
        </span>
      </td>
    </tr>
  );
}

function SweepButton({ onSweep, busy }) {
  return (
    <button
      className="primary-button"
      style={{ marginLeft: 8 }}
      disabled={busy}
      onClick={onSweep}
      title="Rule A 해당 건 전체 ai_safe_final_approve 자동 실행"
    >
      {busy ? '처리 중...' : '⚡ 자동 Sweep (Rule A 전체)'}
    </button>
  );
}

export default function PendingEscalationPanel() {
  const { loading, error, data, refresh, lastRefresh } = usePendingEscalation();
  const [actionBusy, setActionBusy] = useState(false);
  const [actionLog, setActionLog] = useState([]);

  const logAction = (msg) =>
    setActionLog((prev) => [
      { time: new Date().toLocaleTimeString(), msg },
      ...prev.slice(0, 19),
    ]);

  const handleApprove = async (item) => {
    setActionBusy(true);
    try {
      // force=true: db-admin 오프라인 시에도 처리 가능하게 강제 전환
      const result = await requestJson(`/api/escalation/${encodeURIComponent(item.raw_record_id)}/approve`, {
        body: { reviewer_id: 'admin:escalation-ui', force: true },
      });
      logAction(`✅ 승인 성공: ${item.raw_record_id} → ${result.status}`);
    } catch (err) {
      logAction(`❌ 승인 실패: ${item.raw_record_id} — ${err.message}`);
    } finally {
      setActionBusy(false);
      refresh();
    }
  };

  const handleReject = async (item) => {
    const reason = window.prompt(`거부 사유를 입력하세요 (${item.raw_record_id}):`, '운영자 escalation 거부');
    if (!reason) return;
    setActionBusy(true);
    try {
      const result = await requestJson(`/api/escalation/${encodeURIComponent(item.raw_record_id)}/reject`, {
        body: { reviewer_id: 'admin:escalation-ui', reason },
      });
      logAction(`🔄 거부 성공: ${item.raw_record_id} → ${result.status}`);
    } catch (err) {
      logAction(`❌ 거부 실패: ${item.raw_record_id} — ${err.message}`);
    } finally {
      setActionBusy(false);
      refresh();
    }
  };

  const handleSweep = async () => {
    setActionBusy(true);
    try {
      const result = await requestJson('/api/escalation/sweep', { body: {} });
      logAction(`⚡ Sweep 완료: 발행=${result.sweep_published}, 실패=${result.sweep_failed}`);
    } catch (err) {
      logAction(`❌ Sweep 실패: ${err.message}`);
    } finally {
      setActionBusy(false);
      refresh();
    }
  };

  const items = data?.items ?? [];
  const alarm = data?.alarm;
  const total = data?.total_pending ?? 0;
  const recent1h = data?.recent_stale_1h_count ?? 0;

  return (
    <section className="panel" id="pending-escalation">
      {/* 헤더 */}
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h2>⏳ pending_db_review Escalation 큐</h2>
          <div className="muted">
            DB-admin 검수 대기 중 정체 건을 표시합니다 — Rule A 자동발행 · Rule B 사람검토 · Rule C 알람
          </div>
        </div>
        <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {lastRefresh && (
            <span className="muted" style={{ fontSize: 11 }}>
              {lastRefresh.toLocaleTimeString()} 갱신
            </span>
          )}
          <button className="primary-button" onClick={refresh} disabled={loading || actionBusy}>
            {loading ? '로딩 중...' : '새로고침'}
          </button>
          <SweepButton onSweep={handleSweep} busy={actionBusy || loading} />
        </span>
      </div>

      {/* 알람 카드 */}
      <AlarmCard alarm={alarm} />

      {/* 오류 표시 */}
      {error && (
        <div className="muted" style={{ color: '#f66', marginBottom: 12 }}>
          오류: {error} — 백엔드 실행 여부를 확인하세요.
        </div>
      )}

      {/* 요약 카운터 */}
      <div className="status-grid" style={{ marginBottom: 16 }}>
        <div className="card status-card">
          <strong>총 정체 건</strong>
          <div style={{ fontSize: 28, fontWeight: 700, margin: '8px 0', color: total > 0 ? '#ff9800' : '#81c784' }}>
            {loading ? '...' : total}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>pending_db_review 합계</div>
        </div>
        <div className="card status-card">
          <strong>최근 1시간 정체</strong>
          <div style={{ fontSize: 28, fontWeight: 700, margin: '8px 0', color: recent1h > 0 ? '#ff9800' : '#81c784' }}>
            {loading ? '...' : recent1h}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>지난 1시간 이내 추가된 건</div>
        </div>
        <div className="card status-card">
          <strong>Rule A (자동발행)</strong>
          <div style={{ fontSize: 28, fontWeight: 700, margin: '8px 0', color: '#4fc3f7' }}>
            {loading ? '...' : items.filter((i) => i.rule === 'auto_publish').length}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>4게이트 통과 · Sweep 자동처리 대상</div>
        </div>
        <div className="card status-card">
          <strong>Rule C (알람)</strong>
          <div style={{ fontSize: 28, fontWeight: 700, margin: '8px 0', color: alarm?.alarm_triggered ? '#f44' : '#81c784' }}>
            {loading ? '...' : items.filter((i) => i.rule === 'alarm').length}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>24시간+ 정체 건</div>
        </div>
      </div>

      {/* 정체 건 테이블 */}
      {items.length === 0 ? (
        <div className="card" style={{ padding: 24, textAlign: 'center', color: '#888' }}>
          🎉 정체 건 없음 — pending_db_review 큐가 비어있습니다.
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #444', textAlign: 'left', background: '#1a1a2e' }}>
                <th style={{ padding: '8px 8px' }}>raw_record_id</th>
                <th style={{ padding: '8px 8px' }}>소스</th>
                <th style={{ padding: '8px 8px' }}>경과시간</th>
                <th style={{ padding: '8px 8px' }}>ingestion_id</th>
                <th style={{ padding: '8px 8px' }}>룰</th>
                <th style={{ padding: '8px 8px' }}>게이트</th>
                <th style={{ padding: '8px 8px' }}>액션</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <EscalationRow
                  key={item.raw_record_id}
                  item={item}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  busy={actionBusy}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 액션 로그 */}
      {actionLog.length > 0 && (
        <div className="card" style={{ marginTop: 12, padding: '8px 12px' }}>
          <strong style={{ fontSize: 12 }}>액션 로그</strong>
          <ul style={{ margin: '4px 0 0', padding: '0 0 0 16px', fontSize: 12, color: '#ccc' }}>
            {actionLog.map((entry, i) => (
              <li key={i} style={{ marginBottom: 2 }}>
                <span style={{ color: '#888', marginRight: 6 }}>{entry.time}</span>
                {entry.msg}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
