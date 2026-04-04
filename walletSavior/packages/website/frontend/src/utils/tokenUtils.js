/**
 * JWT 토큰 유틸리티 — 브라우저 측 편의 함수
 */

/**
 * JWT payload를 검증 없이 디코딩한다.
 * 잘못된 토큰이면 null을 반환한다.
 */
export function decodeTokenPayload(token) {
  try {
    const base64 = token.split('.')[1];
    const json = atob(base64.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json);
  } catch {
    return null;
  }
}

/**
 * 토큰이 bufferMs 이내에 만료되는지 확인한다.
 * 기본 버퍼: 60초.
 */
export function isTokenExpiringSoon(token, bufferMs = 60_000) {
  const payload = decodeTokenPayload(token);
  if (!payload?.exp) return true;
  return Date.now() >= payload.exp * 1000 - bufferMs;
}
