/**
 * PermissionManager 테스트 — 권한 부여/거부/취소
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PermissionManager } from '../runtime/PermissionManager.js';

/** 인메모리 스토리지 모의 */
function createMockStorage() {
  const store = {};
  return {
    getItem: vi.fn((key) => store[key] || null),
    setItem: vi.fn((key, value) => { store[key] = value; }),
    removeItem: vi.fn((key) => { delete store[key]; }),
  };
}

describe('PermissionManager', () => {
  let pm;
  let storage;

  beforeEach(() => {
    storage = createMockStorage();
    pm = new PermissionManager(storage);
  });

  it('초기 상태 — 권한 없음', () => {
    expect(pm.hasPermission('plugin-1', 'read:products')).toBe(false);
    expect(pm.getPermissions('plugin-1')).toEqual([]);
  });

  it('권한 부여 (grantPermission)', () => {
    pm.grantPermission('plugin-1', 'read:products');
    expect(pm.hasPermission('plugin-1', 'read:products')).toBe(true);
  });

  it('중복 권한 부여 시 무시', () => {
    pm.grantPermission('plugin-1', 'read:products');
    pm.grantPermission('plugin-1', 'read:products');
    expect(pm.getPermissions('plugin-1')).toEqual(['read:products']);
  });

  it('유효하지 않은 권한 부여 시 에러', () => {
    expect(() => pm.grantPermission('plugin-1', 'invalid:perm')).toThrow('유효하지 않은 권한');
  });

  it('여러 권한 한 번에 부여 (grantPermissions)', () => {
    pm.grantPermissions('plugin-1', ['read:products', 'read:prices']);
    expect(pm.hasAllPermissions('plugin-1', ['read:products', 'read:prices'])).toBe(true);
  });

  it('hasAllPermissions — 일부 누락 시 false', () => {
    pm.grantPermission('plugin-1', 'read:products');
    expect(pm.hasAllPermissions('plugin-1', ['read:products', 'read:prices'])).toBe(false);
  });

  it('권한 취소 (revokePermission)', () => {
    pm.grantPermission('plugin-1', 'read:products');
    pm.revokePermission('plugin-1', 'read:products');
    expect(pm.hasPermission('plugin-1', 'read:products')).toBe(false);
  });

  it('모든 권한 취소 (revokeAllPermissions)', () => {
    pm.grantPermissions('plugin-1', ['read:products', 'read:prices']);
    pm.revokeAllPermissions('plugin-1');
    expect(pm.getPermissions('plugin-1')).toEqual([]);
  });

  it('권한 정보 localStorage에 저장', () => {
    pm.grantPermission('plugin-1', 'read:products');
    expect(storage.setItem).toHaveBeenCalled();
  });

  it('requestPermissions — 프롬프트 핸들러 승인', async () => {
    pm.setPromptHandler(vi.fn().mockResolvedValue(true));
    const result = await pm.requestPermissions('plugin-1', ['read:products']);
    expect(result.granted).toBe(true);
    expect(pm.hasPermission('plugin-1', 'read:products')).toBe(true);
  });

  it('requestPermissions — 프롬프트 핸들러 거부', async () => {
    pm.setPromptHandler(vi.fn().mockResolvedValue(false));
    const result = await pm.requestPermissions('plugin-1', ['read:products']);
    expect(result.granted).toBe(false);
    expect(pm.hasPermission('plugin-1', 'read:products')).toBe(false);
  });

  it('requestPermissions — 핸들러 없으면 거부', async () => {
    const result = await pm.requestPermissions('plugin-1', ['read:products']);
    expect(result.granted).toBe(false);
  });

  it('requestPermissions — 이미 부여된 권한은 재요청하지 않음', async () => {
    pm.grantPermission('plugin-1', 'read:products');
    const handler = vi.fn();
    pm.setPromptHandler(handler);
    const result = await pm.requestPermissions('plugin-1', ['read:products']);
    expect(result.granted).toBe(true);
    expect(handler).not.toHaveBeenCalled();
  });

  it('getAllGrants()로 전체 권한 조회', () => {
    pm.grantPermission('p1', 'read:products');
    pm.grantPermission('p2', 'read:prices');
    const grants = pm.getAllGrants();
    expect(grants).toEqual({
      p1: ['read:products'],
      p2: ['read:prices'],
    });
  });

  it('reset()으로 전체 초기화', () => {
    pm.grantPermission('p1', 'read:products');
    pm.reset();
    expect(pm.getAllGrants()).toEqual({});
  });

  it('존재하지 않는 플러그인 권한 취소 시 오류 없음', () => {
    expect(() => pm.revokePermission('nonexistent', 'read:products')).not.toThrow();
  });
});
