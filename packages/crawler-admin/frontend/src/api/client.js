const API_BASE = '/api';

export const api = {
  // 크롤러 목록
  getCrawlers: () => fetch(`${API_BASE}/crawlers`).then(r => r.json()),
  // 크롤러 실행
  runCrawler: (id) => fetch(`${API_BASE}/crawlers/${id}/run`, { method: 'POST' }).then(r => r.json()),
  // 크롤러 상태
  getCrawlerStatus: (id) => fetch(`${API_BASE}/crawlers/${id}/status`).then(r => r.json()),
  // 로그
  getLogs: (params) => fetch(`${API_BASE}/logs?${new URLSearchParams(params)}`).then(r => r.json()),
  // 스케줄
  getSchedules: () => fetch(`${API_BASE}/schedules`).then(r => r.json()),
  createSchedule: (data) => fetch(`${API_BASE}/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  updateSchedule: (name, data) => fetch(`${API_BASE}/schedules/${name}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  deleteSchedule: (name) => fetch(`${API_BASE}/schedules/${name}`, { method: 'DELETE' }),
  // 대기열
  getIngestions: (params) => fetch(`${API_BASE}/ingestions?${new URLSearchParams(params)}`).then(r => r.json()),
  getIngestion: (id) => fetch(`${API_BASE}/ingestions/${id}`).then(r => r.json()),
  reviewIngestion: (id, data) => fetch(`${API_BASE}/ingestions/${id}/crawler-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
};
