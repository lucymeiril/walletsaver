import { useEffect, useState } from 'react'
import {
  fetchAuditLog,
  fetchReports,
  resolveReport,
  banUser,
  unbanUser,
} from '../api/client'
import type { AuditEntry, Report } from '../types'

type Tab = 'reports' | 'audit'

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>('reports')
  const [reports, setReports] = useState<Report[]>([])
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [userId, setUserId] = useState('')

  function reload() {
    fetchReports('open').then(setReports).catch(() => setReports([]))
    fetchAuditLog().then(setAudit).catch(() => setAudit([]))
  }

  useEffect(reload, [])

  async function handleResolve(r: Report, action: 'hide_target' | 'delete_target' | 'dismiss' | 'ban_user') {
    await resolveReport(r.id, action)
    reload()
  }

  return (
    <div style={{ maxWidth: 900, margin: '20px auto', padding: 20 }}>
      <h2>관리자</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button onClick={() => setTab('reports')} style={{ padding: '8px 12px', borderRadius: 8, background: tab === 'reports' ? '#374151' : '#f3f4f6', color: tab === 'reports' ? 'white' : '#374151', border: 'none', cursor: 'pointer' }}>신고</button>
        <button onClick={() => setTab('audit')} style={{ padding: '8px 12px', borderRadius: 8, background: tab === 'audit' ? '#374151' : '#f3f4f6', color: tab === 'audit' ? 'white' : '#374151', border: 'none', cursor: 'pointer' }}>감사 로그</button>
      </div>

      {tab === 'reports' && (
        <div data-testid="reports-list" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {reports.length === 0 && <div style={{ color: '#6b7280' }}>대기 중인 신고가 없습니다.</div>}
          {reports.map((r) => (
            <div key={r.id} style={{ padding: 12, borderRadius: 12, background: '#f9fafb', border: '1px solid #e5e7eb' }}>
              <div style={{ fontSize: 13, color: '#6b7280' }}>
                {r.target_kind} #{r.target_id} · {r.created_at}
              </div>
              <div style={{ marginTop: 4 }}>{r.reason || '(사유 없음)'}</div>
              <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button onClick={() => handleResolve(r, 'hide_target')} style={{ padding: '4px 10px', borderRadius: 6, cursor: 'pointer' }}>숨김</button>
                <button onClick={() => handleResolve(r, 'delete_target')} style={{ padding: '4px 10px', borderRadius: 6, cursor: 'pointer' }}>삭제</button>
                <button onClick={() => handleResolve(r, 'dismiss')} style={{ padding: '4px 10px', borderRadius: 6, cursor: 'pointer' }}>기각</button>
                <button onClick={() => handleResolve(r, 'ban_user')} style={{ padding: '4px 10px', borderRadius: 6, cursor: 'pointer', background: '#fee2e2' }}>유저 차단</button>
              </div>
            </div>
          ))}

          <hr style={{ margin: '20px 0' }} />
          <h3>사용자 차단/해제</h3>
          <div style={{ display: 'flex', gap: 8 }}>
            <input placeholder="user_id" value={userId} onChange={(e) => setUserId(e.target.value)} style={{ flex: 1, padding: 8, borderRadius: 8, border: '1px solid #d1d5db' }} />
            <button onClick={async () => { if (userId) { await banUser(userId); reload() } }} style={{ padding: '6px 12px', borderRadius: 8, cursor: 'pointer' }}>차단</button>
            <button onClick={async () => { if (userId) { await unbanUser(userId); reload() } }} style={{ padding: '6px 12px', borderRadius: 8, cursor: 'pointer' }}>해제</button>
          </div>
        </div>
      )}

      {tab === 'audit' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {audit.length === 0 && <div style={{ color: '#6b7280' }}>로그가 없습니다.</div>}
          {audit.map((a) => (
            <div key={a.id} style={{ padding: 10, background: '#f9fafb', borderRadius: 8, fontSize: 13 }}>
              <strong>{a.action}</strong> · {a.target_kind || '-'} #{a.target_id || '-'} · {a.created_at}
              {a.note && <div style={{ color: '#6b7280' }}>{a.note}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
