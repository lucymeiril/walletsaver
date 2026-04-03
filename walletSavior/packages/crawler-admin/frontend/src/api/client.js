const API_BASE = '/api';

export const api = {
  // 크롤러 목록
  getCrawlers: () => fetch(`${API_BASE}/crawlers`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 실행
  runCrawler: (id) => fetch(`${API_BASE}/crawlers/${id}/run`, { method: 'POST' }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 상태
  getCrawlerStatus: (id) => fetch(`${API_BASE}/crawlers/${id}/status`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 토글
  toggleCrawler: (id, status) => fetch(`${API_BASE}/crawlers/${id}/toggle`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 벌크 실행
  bulkRunCrawlers: (ids) => fetch(`${API_BASE}/crawlers/bulk-run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ crawler_ids: ids }),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 설정
  getCrawlerSettings: (id) => fetch(`${API_BASE}/crawlers/${id}/settings`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  updateCrawlerSettings: (id, data) => fetch(`${API_BASE}/crawlers/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 대시보드 통계
  getDashboardStats: (params = {}) => fetch(`${API_BASE}/dashboard/stats?${new URLSearchParams(params)}`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 로그
  getLogs: (params) => fetch(`${API_BASE}/logs?${new URLSearchParams(params)}`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 로그 CSV 내보내기
  exportLogsCsv: (params = {}) => fetch(`${API_BASE}/logs/export?${new URLSearchParams(params)}`).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.blob();
  }),
  // 스케줄
  getSchedules: () => fetch(`${API_BASE}/schedules`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  createSchedule: (data) => fetch(`${API_BASE}/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  updateSchedule: (name, data) => fetch(`${API_BASE}/schedules/${name}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  deleteSchedule: (name) => fetch(`${API_BASE}/schedules/${name}`, { method: 'DELETE' }),
  toggleSchedule: (name, enabled) => fetch(`${API_BASE}/schedules/${name}/toggle`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 플러그인
  getPlugins: () => fetch(`${API_BASE}/plugins`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  togglePlugin: (id, status) => fetch(`${API_BASE}/plugins/${id}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  updatePluginSettings: (id, data) => fetch(`${API_BASE}/plugins/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 대기열
  getIngestions: (params) => fetch(`${API_BASE}/ingestions?${new URLSearchParams(params)}`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  getIngestion: (id) => fetch(`${API_BASE}/ingestions/${id}`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  reviewIngestion: (id, data) => fetch(`${API_BASE}/ingestions/${id}/crawler-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
};
