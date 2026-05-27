/**
 * PluginStore 테스트 — Zustand 스토어 액션
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { usePluginStore } from '../manager/PluginStore.js';

const mockPlugin = {
  id: 'test-plugin',
  name: '테스트 플러그인',
  version: '1.0.0',
  description: '테스트용',
  author: 'tester',
  slot: 'dashboard-widget',
  permissions: ['read:products'],
  entry: '/plugins/test/index.html',
  config: { refreshInterval: 30 },
};

describe('PluginStore', () => {
  beforeEach(() => {
    // 스토어 초기화
    usePluginStore.setState({ plugins: [] });
  });

  it('초기 상태 — 빈 플러그인 목록', () => {
    const state = usePluginStore.getState();
    expect(state.plugins).toEqual([]);
  });

  it('플러그인 설치 (installPlugin)', () => {
    const { installPlugin } = usePluginStore.getState();
    installPlugin(mockPlugin);
    const { plugins } = usePluginStore.getState();
    expect(plugins).toHaveLength(1);
    expect(plugins[0].id).toBe('test-plugin');
    expect(plugins[0].active).toBe(false);
    expect(plugins[0].installedAt).toBeDefined();
  });

  it('중복 설치 방지', () => {
    const { installPlugin } = usePluginStore.getState();
    installPlugin(mockPlugin);
    installPlugin(mockPlugin);
    expect(usePluginStore.getState().plugins).toHaveLength(1);
  });

  it('플러그인 제거 (uninstallPlugin)', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    state.uninstallPlugin('test-plugin');
    expect(usePluginStore.getState().plugins).toHaveLength(0);
  });

  it('플러그인 활성화 (enablePlugin)', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    state.enablePlugin('test-plugin');
    const plugin = usePluginStore.getState().plugins[0];
    expect(plugin.active).toBe(true);
  });

  it('플러그인 비활성화 (disablePlugin)', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    state.enablePlugin('test-plugin');
    state.disablePlugin('test-plugin');
    const plugin = usePluginStore.getState().plugins[0];
    expect(plugin.active).toBe(false);
  });

  it('설정 업데이트 (updatePluginConfig)', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    state.updatePluginConfig('test-plugin', { refreshInterval: 60, newOption: true });
    const plugin = usePluginStore.getState().plugins[0];
    expect(plugin.config.refreshInterval).toBe(60);
    expect(plugin.config.newOption).toBe(true);
  });

  it('getPlugin()으로 개별 조회', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    const plugin = usePluginStore.getState().getPlugin('test-plugin');
    expect(plugin).toBeDefined();
    expect(plugin.id).toBe('test-plugin');
  });

  it('getActivePlugins() — 활성 플러그인만 반환', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    state.installPlugin({ ...mockPlugin, id: 'plugin-2', name: '플러그인 2' });
    state.enablePlugin('test-plugin');
    const active = usePluginStore.getState().getActivePlugins();
    expect(active).toHaveLength(1);
    expect(active[0].id).toBe('test-plugin');
  });

  it('getActivePluginsBySlot() — 슬롯별 필터링', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    state.installPlugin({ ...mockPlugin, id: 'sidebar-plugin', slot: 'sidebar' });
    state.enablePlugin('test-plugin');
    state.enablePlugin('sidebar-plugin');
    const widgets = usePluginStore.getState().getActivePluginsBySlot('dashboard-widget');
    expect(widgets).toHaveLength(1);
    expect(widgets[0].id).toBe('test-plugin');
  });

  it('isInstalled() 확인', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    expect(usePluginStore.getState().isInstalled('test-plugin')).toBe(true);
    expect(usePluginStore.getState().isInstalled('other')).toBe(false);
  });

  it('버전 업데이트 (updatePluginVersion)', () => {
    const state = usePluginStore.getState();
    state.installPlugin(mockPlugin);
    state.updatePluginVersion('test-plugin', '2.0.0', '/plugins/test/v2/index.html');
    const plugin = usePluginStore.getState().plugins[0];
    expect(plugin.version).toBe('2.0.0');
    expect(plugin.entry).toBe('/plugins/test/v2/index.html');
    expect(plugin.updatedAt).toBeDefined();
  });
});
