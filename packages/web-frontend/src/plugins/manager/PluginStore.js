/**
 * PluginStore — 플러그인 상태 관리 (Zustand)
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const usePluginStore = create(
  persist(
    (set, get) => ({
      /** 설치된 플러그인 목록 */
      plugins: [],

      /** 플러그인 설치 */
      installPlugin: (plugin) =>
        set((state) => {
          if (state.plugins.some((p) => p.id === plugin.id)) {
            return state; // 이미 설치됨
          }
          return {
            plugins: [
              ...state.plugins,
              { ...plugin, active: false, installedAt: Date.now() },
            ],
          };
        }),

      /** 플러그인 제거 */
      uninstallPlugin: (pluginId) =>
        set((state) => ({
          plugins: state.plugins.filter((p) => p.id !== pluginId),
        })),

      /** 플러그인 활성화 */
      enablePlugin: (pluginId) =>
        set((state) => ({
          plugins: state.plugins.map((p) =>
            p.id === pluginId ? { ...p, active: true } : p
          ),
        })),

      /** 플러그인 비활성화 */
      disablePlugin: (pluginId) =>
        set((state) => ({
          plugins: state.plugins.map((p) =>
            p.id === pluginId ? { ...p, active: false } : p
          ),
        })),

      /** 플러그인 설정 업데이트 */
      updatePluginConfig: (pluginId, config) =>
        set((state) => ({
          plugins: state.plugins.map((p) =>
            p.id === pluginId ? { ...p, config: { ...p.config, ...config } } : p
          ),
        })),

      /** 플러그인 ID로 조회 */
      getPlugin: (pluginId) => get().plugins.find((p) => p.id === pluginId),

      /** 활성 플러그인 목록 */
      getActivePlugins: () => get().plugins.filter((p) => p.active),

      /** 슬롯별 활성 플러그인 */
      getActivePluginsBySlot: (slot) =>
        get().plugins.filter((p) => p.active && p.slot === slot),

      /** 설치 여부 확인 */
      isInstalled: (pluginId) => get().plugins.some((p) => p.id === pluginId),

      /** 플러그인 버전 업데이트 */
      updatePluginVersion: (pluginId, newVersion, newEntry) =>
        set((state) => ({
          plugins: state.plugins.map((p) =>
            p.id === pluginId
              ? { ...p, version: newVersion, entry: newEntry || p.entry, updatedAt: Date.now() }
              : p
          ),
        })),
    }),
    {
      name: 'wallet-savior-plugins',
      partialize: (state) => ({
        plugins: state.plugins,
      }),
    }
  )
);

export default usePluginStore;
