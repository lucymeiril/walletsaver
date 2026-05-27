/**
 * PermissionManager — 플러그인 권한 관리 시스템
 */

import { VALID_PERMISSIONS } from '../manifest.schema.js';

const STORAGE_KEY = 'wallet-savior-plugin-permissions';

export class PermissionManager {
  constructor(storage = null) {
    this._storage = storage || (typeof localStorage !== 'undefined' ? localStorage : null);
    this._grants = this._load();
    this._promptHandler = null;
  }

  /** 저장소에서 권한 정보 로드 */
  _load() {
    try {
      if (!this._storage) return {};
      const data = this._storage.getItem(STORAGE_KEY);
      return data ? JSON.parse(data) : {};
    } catch {
      return {};
    }
  }

  /** 저장소에 권한 정보 저장 */
  _save() {
    try {
      if (this._storage) {
        this._storage.setItem(STORAGE_KEY, JSON.stringify(this._grants));
      }
    } catch {
      // 저장소 접근 실패 무시
    }
  }

  /** 권한 프롬프트 핸들러 설정 */
  setPromptHandler(handler) {
    this._promptHandler = handler;
  }

  /** 플러그인의 특정 권한 확인 */
  hasPermission(pluginId, permission) {
    const pluginGrants = this._grants[pluginId];
    if (!pluginGrants) return false;
    return pluginGrants.includes(permission);
  }

  /** 플러그인의 모든 권한 확인 */
  hasAllPermissions(pluginId, permissions) {
    return permissions.every((p) => this.hasPermission(pluginId, p));
  }

  /** 권한 부여 */
  grantPermission(pluginId, permission) {
    if (!VALID_PERMISSIONS.includes(permission)) {
      throw new Error(`유효하지 않은 권한: ${permission}`);
    }
    if (!this._grants[pluginId]) {
      this._grants[pluginId] = [];
    }
    if (!this._grants[pluginId].includes(permission)) {
      this._grants[pluginId].push(permission);
      this._save();
    }
  }

  /** 여러 권한 한 번에 부여 */
  grantPermissions(pluginId, permissions) {
    permissions.forEach((p) => this.grantPermission(pluginId, p));
  }

  /** 특정 권한 취소 */
  revokePermission(pluginId, permission) {
    if (!this._grants[pluginId]) return;
    this._grants[pluginId] = this._grants[pluginId].filter((p) => p !== permission);
    if (this._grants[pluginId].length === 0) {
      delete this._grants[pluginId];
    }
    this._save();
  }

  /** 플러그인의 모든 권한 취소 */
  revokeAllPermissions(pluginId) {
    delete this._grants[pluginId];
    this._save();
  }

  /** 플러그인에 부여된 권한 목록 반환 */
  getPermissions(pluginId) {
    return [...(this._grants[pluginId] || [])];
  }

  /** 권한 요청 (프롬프트 핸들러를 통해 사용자 확인) */
  async requestPermissions(pluginId, permissions) {
    const needed = permissions.filter((p) => !this.hasPermission(pluginId, p));
    if (needed.length === 0) return { granted: true, permissions: [] };

    if (this._promptHandler) {
      const approved = await this._promptHandler(pluginId, needed);
      if (approved) {
        this.grantPermissions(pluginId, needed);
        return { granted: true, permissions: needed };
      }
      return { granted: false, permissions: needed };
    }

    // 프롬프트 핸들러 없으면 거부
    return { granted: false, permissions: needed };
  }

  /** 모든 플러그인 권한 정보 반환 */
  getAllGrants() {
    return JSON.parse(JSON.stringify(this._grants));
  }

  /** 전체 초기화 */
  reset() {
    this._grants = {};
    this._save();
  }
}

export default PermissionManager;
