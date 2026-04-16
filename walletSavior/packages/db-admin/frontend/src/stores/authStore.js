/**
 * DB-Admin JWT 인증 스토어
 * sessionStorage 기반 — 탭 종료 시 자동 로그아웃
 * 개발 환경: 시드 계정으로 자동 로그인
 */

const STORAGE_KEY_ACCESS  = 'db_admin_access_token';
const STORAGE_KEY_REFRESH = 'db_admin_refresh_token';
const API_BASE = '/api';

// 개발 전용 시드 계정 — 프론트는 배포하지 않으므로 하드코딩 허용
const DEV_EMAIL = 'admin@walletsavior.com';
const DEV_PASSWORD = 'admin1234!';

const listeners = new Set();

function notify() {
  listeners.forEach(fn => fn());
}

/** JWT payload 디코딩 (exp 확인용) */
function decodePayload(token) {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(base64));
  } catch {
    return null;
  }
}

/** 토큰 만료까지 남은 ms (만료됐으면 음수) */
function msUntilExpiry(token) {
  const payload = decodePayload(token);
  if (!payload?.exp) return -1;
  return payload.exp * 1000 - Date.now();
}

let refreshTimer = null;

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  const token = sessionStorage.getItem(STORAGE_KEY_ACCESS);
  if (!token) return;

  const ms = msUntilExpiry(token);
  // 만료 60초 전에 갱신, 최소 5초 후
  const delay = Math.max(ms - 60_000, 5_000);
  refreshTimer = setTimeout(doRefresh, delay);
}

async function doRefresh() {
  const refreshToken = sessionStorage.getItem(STORAGE_KEY_REFRESH);
  if (!refreshToken) { logout(); return; }

  try {
    const resp = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!resp.ok) { logout(); return; }

    const data = await resp.json();
    sessionStorage.setItem(STORAGE_KEY_ACCESS, data.access_token);
    if (data.refresh_token) {
      sessionStorage.setItem(STORAGE_KEY_REFRESH, data.refresh_token);
    }
    scheduleRefresh();
    notify();
  } catch {
    logout();
  }
}

/** 로그인 — 성공 시 토큰 저장, 실패 시 에러 throw */
export async function login(email, password) {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!resp.ok) {
    let msg = '로그인에 실패했습니다.';
    try {
      const data = await resp.json();
      msg = data.detail || data.message || msg;
    } catch { /* ignore */ }
    throw new Error(msg);
  }

  const data = await resp.json();
  sessionStorage.setItem(STORAGE_KEY_ACCESS, data.access_token);
  if (data.refresh_token) {
    sessionStorage.setItem(STORAGE_KEY_REFRESH, data.refresh_token);
  }
  scheduleRefresh();
  notify();
}

export function logout() {
  clearTimeout(refreshTimer);
  sessionStorage.removeItem(STORAGE_KEY_ACCESS);
  sessionStorage.removeItem(STORAGE_KEY_REFRESH);
  notify();
}

export function isAuthenticated() {
  const token = sessionStorage.getItem(STORAGE_KEY_ACCESS);
  if (!token) return false;
  return msUntilExpiry(token) > 0;
}

export function getAccessToken() {
  return sessionStorage.getItem(STORAGE_KEY_ACCESS);
}

/** 컴포넌트 리렌더 훅 */
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** 개발 환경 자동 로그인 — 앱 로드 시 호출 */
export async function autoLoginDev() {
  if (isAuthenticated()) return;
  try {
    await login(DEV_EMAIL, DEV_PASSWORD);
  } catch {
    console.warn('[authStore] 자동 로그인 실패 — 수동 로그인 필요');
  }
}

// 앱 로드 시 기존 토큰이 있으면 갱신 스케줄 등록
if (isAuthenticated()) {
  scheduleRefresh();
}
