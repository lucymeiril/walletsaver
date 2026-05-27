/**
 * PluginHost — 플러그인 슬롯 관리 컨테이너
 * 이름 기반 슬롯에 플러그인을 배치하고 생명주기 관리
 */

import { useEffect, useCallback, useRef } from 'react';
import PluginSandbox from './PluginSandbox.jsx';
import { PluginAPI } from '../sdk/PluginAPI.js';
import { usePluginStore } from '../manager/PluginStore.js';
import s from './PluginHost.module.css';

/** 유효한 슬롯 이름 */
export const VALID_SLOTS = [
  'header',
  'sidebar',
  'footer',
  'dashboard-widget',
  'price-overlay',
  'hotdeal-card-extra',
];

export default function PluginHost({ slot, className = '' }) {
  const pluginApiRef = useRef(null);
  const plugins = usePluginStore((state) => state.plugins);
  const activePlugins = usePluginStore((state) => state.getActivePluginsBySlot(slot));

  // PluginAPI 인스턴스 생성
  useEffect(() => {
    pluginApiRef.current = new PluginAPI();
    return () => {
      pluginApiRef.current?.destroy();
    };
  }, []);

  const handlePluginLoad = useCallback(
    (pluginId) => (iframe) => {
      if (pluginApiRef.current && iframe?.contentWindow) {
        pluginApiRef.current.createBridge(pluginId, iframe.contentWindow);
      }
    },
    []
  );

  const handlePluginError = useCallback(
    (pluginId) => (error) => {
      console.error(`[PluginHost] 플러그인 오류 (${pluginId}):`, error);
    },
    []
  );

  if (!VALID_SLOTS.includes(slot)) {
    console.warn(`[PluginHost] 유효하지 않은 슬롯: ${slot}`);
    return null;
  }

  if (activePlugins.length === 0) return null;

  return (
    <div className={`${s.host} ${s[slot] || ''} ${className}`} data-slot={slot}>
      {activePlugins.map((plugin) => (
        <div key={plugin.id} className={s.pluginWrapper}>
          <PluginSandbox
            pluginId={plugin.id}
            src={plugin.entry}
            permissions={plugin.permissions || []}
            width="100%"
            height={plugin.config?.height || 200}
            onLoad={handlePluginLoad(plugin.id)}
            onError={handlePluginError(plugin.id)}
          />
        </div>
      ))}
    </div>
  );
}
