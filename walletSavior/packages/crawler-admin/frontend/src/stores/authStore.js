/**
 * Crawler-Admin API Key 인증 스토어
 * sessionStorage 기반 — 탭 종료 시 자동 로그아웃
 * 개발 환경: DEV_API_KEY로 자동 로그인
 */

const STORAGE_KEY = 'crawler_admin_api_key';
const API_BASE = '/api';

// 개발 전용 — 프론트는 배포하지 않으므로 하드코딩 허용
const DEV_API_KEY = 'walletsavior-dev-crawler-key-2025';

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

/** 개발 환경 자동 로그인 — 앱 로드 시 호출 */
export async function autoLoginDev() {
  if (isAuthenticated()) return;
  try {
    await login(DEV_API_KEY);
  } catch {
    // 서버 미기동 시 무시 — 수동 로그인 폴백
    console.warn('[authStore] 자동 로그인 실패 — 수동 로그인 필요');
  }
}
