/**
 * PluginSandbox — 플러그인을 샌드박스 iframe으로 렌더링하는 컴포넌트
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import s from './PluginSandbox.module.css';

const DEFAULT_SANDBOX = 'allow-scripts allow-forms';
const MIN_WIDTH = 100;
const MIN_HEIGHT = 50;
const MAX_WIDTH = 1200;
const MAX_HEIGHT = 800;

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

export default function PluginSandbox({
  pluginId,
  src,
  permissions = [],
  width = '100%',
  height = 300,
  minWidth = MIN_WIDTH,
  minHeight = MIN_HEIGHT,
  maxWidth = MAX_WIDTH,
  maxHeight = MAX_HEIGHT,
  onLoad,
  onError,
  className = '',
}) {
  const iframeRef = useRef(null);
  const [status, setStatus] = useState('loading'); // loading | ready | error

  // CSP 기반 sandbox 속성 구성
  const sandboxAttr = buildSandboxAttr(permissions);

  const handleLoad = useCallback(() => {
    setStatus('ready');
    onLoad?.(iframeRef.current);
  }, [onLoad]);

  const handleError = useCallback(() => {
    setStatus('error');
    onError?.(new Error('플러그인 로드 실패'));
  }, [onError]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    iframe.addEventListener('load', handleLoad);
    iframe.addEventListener('error', handleError);
    return () => {
      iframe.removeEventListener('load', handleLoad);
      iframe.removeEventListener('error', handleError);
    };
  }, [handleLoad, handleError]);

  const constrainedHeight = typeof height === 'number' ? clamp(height, minHeight, maxHeight) : height;
  const constrainedWidth = typeof width === 'number' ? clamp(width, minWidth, maxWidth) : width;

  return (
    <div
      className={`${s.container} ${className}`}
      data-plugin-id={pluginId}
      data-status={status}
    >
      {status === 'loading' && (
        <div className={s.loading}>
          <div className={s.spinner} />
          <span>플러그인 로딩 중...</span>
        </div>
      )}
      {status === 'error' && (
        <div className={s.error}>
          <span>⚠️ 플러그인을 불러올 수 없습니다</span>
          <button
            className={s.retryBtn}
            onClick={() => {
              setStatus('loading');
              if (iframeRef.current) {
                iframeRef.current.src = src;
              }
            }}
          >
            다시 시도
          </button>
        </div>
      )}
      <iframe
        ref={iframeRef}
        src={src}
        sandbox={sandboxAttr}
        title={`플러그인: ${pluginId}`}
        style={{
          width: constrainedWidth,
          height: constrainedHeight,
          border: 'none',
          display: status === 'error' ? 'none' : 'block',
        }}
        referrerPolicy="no-referrer"
      />
    </div>
  );
}

/** 권한에 따른 sandbox 속성 구성 */
function buildSandboxAttr(permissions) {
  const parts = ['allow-scripts'];
  if (permissions.includes('network:external')) {
    parts.push('allow-same-origin');
  }
  if (permissions.includes('write:preferences')) {
    parts.push('allow-forms');
  }
  return parts.join(' ');
}

export { buildSandboxAttr };
