/**
 * PluginSDKLoader — 플러그인 HTML에서 로드하는 SDK 스크립트
 * 플러그인 내부에서 WalletSavior 글로벌 객체를 통해 호스트 API 접근
 *
 * 사용법 (플러그인 HTML에서):
 *   <script src="PluginSDKLoader.js"></script>
 *   <script>
 *     WalletSavior.getTheme().then(theme => console.log(theme));
 *   </script>
 */

(function () {
  'use strict';

  let messageCounter = 0;
  const pendingRequests = new Map();
  const eventListeners = new Map();
  const DEFAULT_TIMEOUT = 5000;

  function generateId() {
    return `msg_${++messageCounter}_${Date.now()}`;
  }

  function sendRequest(type, payload = {}, timeout = DEFAULT_TIMEOUT) {
    return new Promise((resolve, reject) => {
      const id = generateId();
      const timer = setTimeout(() => {
        pendingRequests.delete(id);
        reject(new Error(`요청 시간 초과: ${type}`));
      }, timeout);

      pendingRequests.set(id, { resolve, reject, timer });

      window.parent.postMessage(
        {
          id,
          type,
          payload,
          direction: 'request',
          source: 'wallet-savior',
        },
        document.referrer ? new URL(document.referrer).origin : window.location.origin
      );
    });
  }

  // 부모로부터 메시지 수신
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data || data.source !== 'wallet-savior') return;

    // 응답 메시지 처리
    if (data.direction === 'response') {
      const pending = pendingRequests.get(data.id);
      if (pending) {
        clearTimeout(pending.timer);
        pendingRequests.delete(data.id);
        if (data.error) {
          pending.reject(new Error(data.error));
        } else {
          pending.resolve(data.payload);
        }
      }
      return;
    }

    // push 이벤트 처리 (예: themeChanged)
    if (data.direction === 'push') {
      const listeners = eventListeners.get(data.type);
      if (listeners) {
        listeners.forEach((cb) => {
          try {
            cb(data.payload);
          } catch (e) {
            console.error(`[WalletSavior SDK] 이벤트 핸들러 오류 (${data.type}):`, e);
          }
        });
      }
    }
  });

  /** WalletSavior 글로벌 SDK 객체 */
  const WalletSavior = {
    getTheme() {
      return sendRequest('getTheme');
    },

    getUserPreferences() {
      return sendRequest('getUserPreferences');
    },

    getProductData(productId) {
      return sendRequest('getProductData', { productId });
    },

    getPriceData(productId) {
      return sendRequest('getPriceData', { productId });
    },

    getHotdeals(filters) {
      return sendRequest('getHotdeals', { filters });
    },

    showToast(message, type = 'info') {
      return sendRequest('showToast', { message, type });
    },

    navigateTo(path) {
      return sendRequest('navigateTo', { path });
    },

    onThemeChange(callback) {
      if (typeof callback !== 'function') {
        throw new Error('콜백 함수가 필요합니다');
      }
      if (!eventListeners.has('themeChanged')) {
        eventListeners.set('themeChanged', new Set());
        // 호스트에 구독 등록
        sendRequest('onThemeChange').catch(() => {});
      }
      eventListeners.get('themeChanged').add(callback);
      // 구독 해제 함수 반환
      return () => {
        const listeners = eventListeners.get('themeChanged');
        if (listeners) listeners.delete(callback);
      };
    },

    /** SDK 버전 */
    version: '1.0.0',
  };

  // 글로벌 노출
  if (typeof window !== 'undefined') {
    window.WalletSavior = WalletSavior;
  }

  // 모듈 환경 지원
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = WalletSavior;
  }
})();
