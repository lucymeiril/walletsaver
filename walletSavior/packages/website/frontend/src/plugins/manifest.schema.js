/**
 * 플러그인 매니페스트 스키마 정의 및 검증
 */

/** 유효한 슬롯 목록 */
export const VALID_SLOTS = [
  'header',
  'sidebar',
  'footer',
  'dashboard-widget',
  'price-overlay',
  'hotdeal-card-extra',
];

/** 유효한 권한 목록 */
export const VALID_PERMISSIONS = [
  'read:products',
  'read:prices',
  'read:hotdeals',
  'write:preferences',
  'network:internal',
  'network:external',
];

/** 시맨틱 버전 정규식 */
const SEMVER_REGEX = /^\d+\.\d+\.\d+(-[\w.]+)?(\+[\w.]+)?$/;

/** 플러그인 이름 정규식 (영문 소문자, 숫자, 하이픈) */
const NAME_REGEX = /^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/;

/**
 * 매니페스트 검증 — 오류 목록 반환
 * @param {object} manifest
 * @returns {{ valid: boolean, errors: string[] }}
 */
export function validateManifest(manifest) {
  const errors = [];

  if (!manifest || typeof manifest !== 'object') {
    return { valid: false, errors: ['매니페스트는 객체여야 합니다'] };
  }

  // 필수 필드 검증
  if (!manifest.name || typeof manifest.name !== 'string') {
    errors.push('name은 필수 문자열입니다');
  } else if (!NAME_REGEX.test(manifest.name)) {
    errors.push('name은 영문 소문자, 숫자, 하이픈만 사용 가능합니다');
  }

  if (!manifest.version || typeof manifest.version !== 'string') {
    errors.push('version은 필수 문자열입니다');
  } else if (!SEMVER_REGEX.test(manifest.version)) {
    errors.push('version은 시맨틱 버전 형식이어야 합니다 (예: 1.0.0)');
  }

  if (!manifest.displayName || typeof manifest.displayName !== 'string') {
    errors.push('displayName은 필수 문자열입니다');
  }

  if (!manifest.entry || typeof manifest.entry !== 'string') {
    errors.push('entry는 필수 문자열입니다');
  }

  // 선택 필드 검증
  if (manifest.description !== undefined && typeof manifest.description !== 'string') {
    errors.push('description은 문자열이어야 합니다');
  }

  if (manifest.author !== undefined && typeof manifest.author !== 'string') {
    errors.push('author는 문자열이어야 합니다');
  }

  if (manifest.slot !== undefined) {
    if (typeof manifest.slot !== 'string') {
      errors.push('slot은 문자열이어야 합니다');
    } else if (!VALID_SLOTS.includes(manifest.slot)) {
      errors.push(`slot은 다음 중 하나여야 합니다: ${VALID_SLOTS.join(', ')}`);
    }
  }

  if (manifest.permissions !== undefined) {
    if (!Array.isArray(manifest.permissions)) {
      errors.push('permissions는 배열이어야 합니다');
    } else {
      const invalid = manifest.permissions.filter((p) => !VALID_PERMISSIONS.includes(p));
      if (invalid.length > 0) {
        errors.push(`유효하지 않은 권한: ${invalid.join(', ')}`);
      }
    }
  }

  if (manifest.minAppVersion !== undefined) {
    if (typeof manifest.minAppVersion !== 'string' || !SEMVER_REGEX.test(manifest.minAppVersion)) {
      errors.push('minAppVersion은 시맨틱 버전 형식이어야 합니다');
    }
  }

  if (manifest.icon !== undefined && typeof manifest.icon !== 'string') {
    errors.push('icon은 문자열이어야 합니다');
  }

  if (manifest.config !== undefined && (typeof manifest.config !== 'object' || Array.isArray(manifest.config))) {
    errors.push('config는 객체여야 합니다');
  }

  return { valid: errors.length === 0, errors };
}

export default validateManifest;
