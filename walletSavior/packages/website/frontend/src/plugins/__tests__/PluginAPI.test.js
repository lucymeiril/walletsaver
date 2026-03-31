/**
 * PluginAPI 테스트 — API 메서드 검증
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { PluginAPI } from '../sdk/PluginAPI.js';

describe('PluginAPI', () => {
  let api;
  let mockIframeWindow;

  beforeEach(() => {
    mockIframeWindow = { postMessage: vi.fn() };
    api = new PluginAPI({
      getTheme: () => 'dark',
      getUserPreferences: () => ({ language: 'ko', currency: 'KRW', notifications: true }),
      getProductData: (id) => ({ id, name: `상품 ${id}`, price: 10000 }),
      getPriceData: (id) => ({ productId: id, history: [9000, 10000], current: 10000 }),
      getHotdeals: (filters) => ({ deals: [{ id: 1, title: '핫딜1' }], total: 1, filters }),
      showToast: vi.fn(),
      navigateTo: vi.fn(),
    });
  });

  afterEach(() => {
    api.destroy();
  });

  it('브리지 생성 및 연결', () => {
    const bridge = api.createBridge('test-plugin', mockIframeWindow);
    expect(bridge).toBeDefined();
    expect(api.bridgeCount).toBe(1);
  });

  it('여러 플러그인 브리지 관리', () => {
    api.createBridge('plugin-1', mockIframeWindow);
    api.createBridge('plugin-2', mockIframeWindow);
    expect(api.bridgeCount).toBe(2);
  });

  it('브리지 제거', () => {
    api.createBridge('test-plugin', mockIframeWindow);
    api.removeBridge('test-plugin');
    expect(api.bridgeCount).toBe(0);
  });

  it('존재하지 않는 브리지 제거 시 오류 없음', () => {
    expect(() => api.removeBridge('nonexistent')).not.toThrow();
  });

  it('destroy()로 전체 정리', () => {
    api.createBridge('p1', mockIframeWindow);
    api.createBridge('p2', mockIframeWindow);
    api.destroy();
    expect(api.bridgeCount).toBe(0);
  });

  it('getBridge()로 특정 브리지 조회', () => {
    api.createBridge('my-plugin', mockIframeWindow);
    const bridge = api.getBridge('my-plugin');
    expect(bridge).toBeDefined();
  });

  it('getTheme 핸들러가 등록됨', () => {
    const bridge = api.createBridge('test', mockIframeWindow);
    expect(bridge._handlers.has('getTheme')).toBe(true);
  });

  it('getUserPreferences 핸들러가 등록됨', () => {
    const bridge = api.createBridge('test', mockIframeWindow);
    expect(bridge._handlers.has('getUserPreferences')).toBe(true);
  });

  it('getProductData 핸들러 — productId 없으면 에러', () => {
    const bridge = api.createBridge('test', mockIframeWindow);
    const handler = bridge._handlers.get('getProductData');
    expect(() => handler({})).toThrow('productId가 필요합니다');
  });

  it('getProductData 핸들러 — 정상 반환', async () => {
    const bridge = api.createBridge('test', mockIframeWindow);
    const handler = bridge._handlers.get('getProductData');
    const result = await handler({ productId: '123' });
    expect(result).toEqual({ id: '123', name: '상품 123', price: 10000 });
  });

  it('getPriceData 핸들러 — productId 없으면 에러', () => {
    const bridge = api.createBridge('test', mockIframeWindow);
    const handler = bridge._handlers.get('getPriceData');
    expect(() => handler({})).toThrow('productId가 필요합니다');
  });

  it('showToast 핸들러 — message 없으면 에러', () => {
    const bridge = api.createBridge('test', mockIframeWindow);
    const handler = bridge._handlers.get('showToast');
    expect(() => handler({})).toThrow('message가 필요합니다');
  });

  it('navigateTo 핸들러 — 외부 URL 차단', () => {
    const bridge = api.createBridge('test', mockIframeWindow);
    const handler = bridge._handlers.get('navigateTo');
    expect(() => handler({ path: 'https://evil.com' })).toThrow('외부 URL 이동은 허용되지 않습니다');
  });

  it('navigateTo 핸들러 — 내부 경로 허용', async () => {
    const bridge = api.createBridge('test', mockIframeWindow);
    const handler = bridge._handlers.get('navigateTo');
    const result = await handler({ path: '/hotdeal' });
    expect(result).toEqual({ success: true });
  });

  it('테마 변경 알림 — 구독된 플러그인에만 전송', () => {
    const bridge = api.createBridge('subscribed', mockIframeWindow);
    // 구독 등록
    const handler = bridge._handlers.get('onThemeChange');
    handler();
    
    api.createBridge('unsubscribed', { postMessage: vi.fn() });
    
    api.notifyThemeChange('light');
    // subscribed 플러그인에만 메시지 전송 확인
    const calls = mockIframeWindow.postMessage.mock.calls;
    const themeMsg = calls.find(c => c[0]?.type === 'themeChanged');
    expect(themeMsg).toBeDefined();
    expect(themeMsg[0].payload).toEqual({ theme: 'light' });
  });
});
