/**
 * PluginInstaller — 매니페스트 URL로 플러그인 설치/제거
 */

import { validateManifest } from '../manifest.schema.js';

export class PluginInstaller {
  constructor(pluginStore, permissionManager) {
    this._store = pluginStore;
    this._permissionManager = permissionManager;
    this._cache = new Map();
  }

  /**
   * 매니페스트 URL로 플러그인 설치
   * @param {string} manifestUrl — manifest.json URL
   * @returns {Promise<{ success: boolean, plugin?: object, error?: string }>}
   */
  async install(manifestUrl) {
    try {
      // 1. 매니페스트 다운로드
      const manifest = await this._fetchManifest(manifestUrl);

      // 2. 매니페스트 검증
      const validation = validateManifest(manifest);
      if (!validation.valid) {
        return {
          success: false,
          error: `매니페스트 검증 실패: ${validation.errors.join(', ')}`,
        };
      }

      // 3. 이미 설치 확인
      const state = this._store.getState();
      if (state.isInstalled(manifest.name)) {
        const existing = state.getPlugin(manifest.name);
        if (existing.version === manifest.version) {
          return { success: false, error: '이미 동일 버전이 설치되어 있습니다' };
        }
        // 버전 업데이트
        return this._updatePlugin(manifest, manifestUrl);
      }

      // 4. 권한 요청
      if (manifest.permissions?.length > 0 && this._permissionManager) {
        const result = await this._permissionManager.requestPermissions(
          manifest.name,
          manifest.permissions
        );
        if (!result.granted) {
          return { success: false, error: '권한이 거부되었습니다' };
        }
      }

      // 5. 엔트리 URL 생성
      const baseUrl = manifestUrl.substring(0, manifestUrl.lastIndexOf('/') + 1);
      const entryUrl = manifest.entry.startsWith('http')
        ? manifest.entry
        : `${baseUrl}${manifest.entry}`;

      // 6. 플러그인 데이터 구성
      const pluginData = {
        id: manifest.name,
        name: manifest.displayName || manifest.name,
        version: manifest.version,
        description: manifest.description || '',
        author: manifest.author || '',
        slot: manifest.slot || 'dashboard-widget',
        permissions: manifest.permissions || [],
        entry: entryUrl,
        icon: manifest.icon ? `${baseUrl}${manifest.icon}` : null,
        config: manifest.config || {},
        manifestUrl,
      };

      // 7. 스토어에 설치
      state.installPlugin(pluginData);

      // 8. 캐시 저장
      this._cache.set(manifest.name, manifest);

      return { success: true, plugin: pluginData };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  /** 플러그인 버전 업데이트 */
  async _updatePlugin(manifest, manifestUrl) {
    const baseUrl = manifestUrl.substring(0, manifestUrl.lastIndexOf('/') + 1);
    const entryUrl = manifest.entry.startsWith('http')
      ? manifest.entry
      : `${baseUrl}${manifest.entry}`;

    this._store.getState().updatePluginVersion(manifest.name, manifest.version, entryUrl);
    this._cache.set(manifest.name, manifest);
    return { success: true, plugin: { id: manifest.name, version: manifest.version }, updated: true };
  }

  /** 플러그인 제거 */
  uninstall(pluginId) {
    const state = this._store.getState();
    if (!state.isInstalled(pluginId)) {
      return { success: false, error: '설치되지 않은 플러그인입니다' };
    }
    state.uninstallPlugin(pluginId);
    if (this._permissionManager) {
      this._permissionManager.revokeAllPermissions(pluginId);
    }
    this._cache.delete(pluginId);
    return { success: true };
  }

  /** 매니페스트 다운로드 */
  async _fetchManifest(url) {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`매니페스트 다운로드 실패: ${response.status}`);
    }
    return response.json();
  }

  /** 캐시된 매니페스트 조회 */
  getCachedManifest(pluginId) {
    return this._cache.get(pluginId) || null;
  }
}

export default PluginInstaller;
