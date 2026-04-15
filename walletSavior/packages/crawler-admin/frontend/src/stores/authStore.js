/**
 * Crawler-Admin API Key 인증 스토어
 * sessionStorage 기반 — 탭 종료 시 자동 로그아웃
 */

const STORAGE_KEY = 'crawler_admin_api_key';
const API_BASE = '/api';

const listeners = new Set();

function notify() {
  listeners.forEach(fn => fn());
}

/** API 키로 보호된 엔드포인트 호출하여 유효성 검증 후 저장 */
export async function login(apiKey) {
  const resp = await fetch(`${API_BASE}/crawlers`, {
    headers: { 'X-API-Key': apiKey },
  });

  if (!resp.ok) {
    throw new Error('API 키가 유효하지 않습니다.');
  }

  sessionStorage.setItem(STORAGE_KEY, apiKey);
  notify();
}

export function logout() {
  sessionStorage.removeItem(STORAGE_KEY);
  notify();
}

export function isAuthenticated() {
  return !!sessionStorage.getItem(STORAGE_KEY);
}

export function getApiKey() {
  return sessionStorage.getItem(STORAGE_KEY);
}

/** 컴포넌트 리렌더 훅 */
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
