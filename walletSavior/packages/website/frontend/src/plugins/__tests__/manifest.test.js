/**
 * manifest.schema 테스트 — 매니페스트 검증
 */

import { describe, it, expect } from 'vitest';
import { validateManifest, VALID_SLOTS, VALID_PERMISSIONS } from '../manifest.schema.js';

const validManifest = {
  name: 'my-plugin',
  version: '1.0.0',
  displayName: '나만의 플러그인',
  description: '설명',
  author: '작성자',
  slot: 'dashboard-widget',
  permissions: ['read:products', 'read:prices'],
  entry: 'index.html',
  icon: 'icon.png',
  minAppVersion: '1.0.0',
  config: { refreshInterval: 30 },
};

describe('validateManifest', () => {
  it('유효한 매니페스트 통과', () => {
    const result = validateManifest(validManifest);
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('null 입력 시 실패', () => {
    const result = validateManifest(null);
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('매니페스트는 객체여야 합니다');
  });

  it('name 누락 시 실패', () => {
    const { name, ...rest } = validManifest;
    const result = validateManifest(rest);
    expect(result.valid).toBe(false);
    expect(result.errors.some(e => e.includes('name'))).toBe(true);
  });

  it('name 형식 오류 — 대문자', () => {
    const result = validateManifest({ ...validManifest, name: 'MyPlugin' });
    expect(result.valid).toBe(false);
  });

  it('name 형식 오류 — 특수문자', () => {
    const result = validateManifest({ ...validManifest, name: 'my_plugin!' });
    expect(result.valid).toBe(false);
  });

  it('단일 문자 name 허용', () => {
    const result = validateManifest({ ...validManifest, name: 'x' });
    expect(result.valid).toBe(true);
  });

  it('version 누락 시 실패', () => {
    const { version, ...rest } = validManifest;
    const result = validateManifest(rest);
    expect(result.valid).toBe(false);
  });

  it('version 형식 오류', () => {
    const result = validateManifest({ ...validManifest, version: 'abc' });
    expect(result.valid).toBe(false);
  });

  it('pre-release 버전 허용 (1.0.0-beta.1)', () => {
    const result = validateManifest({ ...validManifest, version: '1.0.0-beta.1' });
    expect(result.valid).toBe(true);
  });

  it('displayName 누락 시 실패', () => {
    const { displayName, ...rest } = validManifest;
    const result = validateManifest(rest);
    expect(result.valid).toBe(false);
  });

  it('entry 누락 시 실패', () => {
    const { entry, ...rest } = validManifest;
    const result = validateManifest(rest);
    expect(result.valid).toBe(false);
  });

  it('유효하지 않은 slot 이름', () => {
    const result = validateManifest({ ...validManifest, slot: 'nonexistent-slot' });
    expect(result.valid).toBe(false);
  });

  it('유효한 모든 슬롯 허용', () => {
    VALID_SLOTS.forEach(slot => {
      const result = validateManifest({ ...validManifest, slot });
      expect(result.valid).toBe(true);
    });
  });

  it('유효하지 않은 권한', () => {
    const result = validateManifest({
      ...validManifest,
      permissions: ['read:products', 'write:admin'],
    });
    expect(result.valid).toBe(false);
    expect(result.errors.some(e => e.includes('write:admin'))).toBe(true);
  });

  it('permissions가 배열이 아닌 경우', () => {
    const result = validateManifest({ ...validManifest, permissions: 'read:products' });
    expect(result.valid).toBe(false);
  });

  it('minAppVersion 형식 오류', () => {
    const result = validateManifest({ ...validManifest, minAppVersion: 'latest' });
    expect(result.valid).toBe(false);
  });

  it('config가 배열이면 실패', () => {
    const result = validateManifest({ ...validManifest, config: [1, 2] });
    expect(result.valid).toBe(false);
  });

  it('최소 필수 필드만으로 통과', () => {
    const result = validateManifest({
      name: 'minimal',
      version: '0.1.0',
      displayName: '최소 플러그인',
      entry: 'index.html',
    });
    expect(result.valid).toBe(true);
  });

  it('VALID_PERMISSIONS 상수 내보내기', () => {
    expect(VALID_PERMISSIONS).toContain('read:products');
    expect(VALID_PERMISSIONS).toContain('network:external');
    expect(VALID_PERMISSIONS).toHaveLength(6);
  });
});
