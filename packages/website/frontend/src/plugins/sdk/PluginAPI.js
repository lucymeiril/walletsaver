/**
 * PluginAPI — 호스트 측에서 플러그인에 노출하는 API
 * MessageBridge 핸들러로 등록하여 플러그인 요청을 처리
 */

import { MessageBridge } from './MessageBridge.js';

// 테마 변경 콜백 목록
const themeChangeCallbacks = new Set();

/** 기본 데이터 제공자 (테스트 및 폴백용) */
const defaultProviders = {
  getTheme: () => document.documentElement.getAttribute('data-theme') || 'dark',
  getUserPreferences: () => ({
    language: 'ko',
    currency: 'KRW',
    notifications: true,
  }),
  getProductData: (productId) => ({
    id: productId,
    name: `상품 ${productId}`,
    price: 0,
    category: 'unknown',
  }),
  getPriceData: (productId) => ({
    productId,
    history: [],
    current: 0,
  }),
  getHotdeals: (filters) => ({
    deals: [],
    total: 0,
    filters: filters || {},
  }),
};

export class PluginAPI {
  constructor(providers = {}) {
    this._providers = { ...defaultProviders, ...providers };
    this._bridges = new Map();
  }

  /** 플러그인 iframe에 대한 브리지 생성 및 API 핸들러 등록 */
  createBridge(pluginId, iframeWindow, allowedOrigins = []) {
    const bridge = new MessageBridge({
      targetWindow: iframeWindow,
      targetOrigin: '*',
      allowedOrigins,
    });

    // API 핸들러 등록
    bridge.on('getTheme', () => this._providers.getTheme());

    bridge.on('getUserPreferences', () => this._providers.getUserPreferences());

    bridge.on('getProductData', (payload) => {
      if (!payload?.productId) throw new Error('productId가 필요합니다');
      return this._providers.getProductData(payload.productId);
    });

    bridge.on('getPriceData', (payload) => {
      if (!payload?.productId) throw new Error('productId가 필요합니다');
      return this._providers.getPriceData(payload.productId);
    });

    bridge.on('getHotdeals', (payload) => {
      return this._providers.getHotdeals(payload?.filters);
    });

    bridge.on('showToast', (payload) => {
      if (!payload?.message) throw new Error('message가 필요합니다');
      if (this._providers.showToast) {
        this._providers.showToast(payload.message, payload.type || 'info');
      }
      return { success: true };
    });

    bridge.on('navigateTo', (payload) => {
      if (!payload?.path) throw new Error('path가 필요합니다');
      // 경로 유효성 검증 — 외부 URL 차단
      if (payload.path.startsWith('http')) {
        throw new Error('외부 URL 이동은 허용되지 않습니다');
      }
      if (this._providers.navigateTo) {
        this._providers.navigateTo(payload.path);
      }
      return { success: true };
    });

    bridge.on('onThemeChange', () => {
      // 테마 변경 구독 등록
      themeChangeCallbacks.add(pluginId);
      return { subscribed: true };
    });

    bridge.connect();
    this._bridges.set(pluginId, bridge);
    return bridge;
  }

  /** 테마 변경 알림 전체 전송 */
  notifyThemeChange(theme) {
    for (const [pluginId, bridge] of this._bridges) {
      if (themeChangeCallbacks.has(pluginId)) {
        bridge.send('themeChanged', { theme });
      }
    }
  }

  /** 특정 플러그인 브리지 해제 */
  removeBridge(pluginId) {
    const bridge = this._bridges.get(pluginId);
    if (bridge) {
      bridge.disconnect();
      this._bridges.delete(pluginId);
      themeChangeCallbacks.delete(pluginId);
    }
  }

  /** 전체 정리 */
  destroy() {
    for (const [pluginId] of this._bridges) {
      this.removeBridge(pluginId);
    }
    themeChangeCallbacks.clear();
  }

  /** 등록된 브리지 수 */
  get bridgeCount() {
    return this._bridges.size;
  }

  /** 특정 브리지 반환 */
  getBridge(pluginId) {
    return this._bridges.get(pluginId);
  }
}

export default PluginAPI;
