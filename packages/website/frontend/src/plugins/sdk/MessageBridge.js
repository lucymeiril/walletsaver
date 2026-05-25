/**
 * MessageBridge — 호스트 ↔ 플러그인 iframe 간 보안 postMessage 통신 계층
 */

const DEFAULT_TIMEOUT = 5000;

export class MessageBridge {
  constructor({ targetWindow, targetOrigin = window.location.origin, allowedOrigins = [window.location.origin] }) {
    this._target = targetWindow;
    this._targetOrigin = targetOrigin;
    this._allowedOrigins = allowedOrigins;
    this._handlers = new Map();
    this._pendingRequests = new Map();
    this._counter = 0;
    this._listener = null;
  }

  /** 메시지 리스너 시작 */
  connect() {
    if (this._listener) return;
    this._listener = (event) => this._onMessage(event);
    window.addEventListener('message', this._listener);
  }

  /** 메시지 리스너 해제 및 정리 */
  disconnect() {
    if (this._listener) {
      window.removeEventListener('message', this._listener);
      this._listener = null;
    }
    // 대기 중인 요청 모두 reject
    for (const [, { reject, timer }] of this._pendingRequests) {
      clearTimeout(timer);
      reject(new Error('Bridge disconnected'));
    }
    this._pendingRequests.clear();
    this._handlers.clear();
  }

  /** origin 검증 — allowedOrigins가 비어있으면 모든 origin 허용 (개발/테스트 모드) */
  isOriginAllowed(origin) {
    if (this._allowedOrigins.length === 0) return true;
    return this._allowedOrigins.includes(origin);
  }

  /** 메시지 핸들러 등록 */
  on(type, handler) {
    this._handlers.set(type, handler);
  }

  /** 핸들러 제거 */
  off(type) {
    this._handlers.delete(type);
  }

  /** 요청 전송 (응답 대기) */
  request(type, payload = {}, timeout = DEFAULT_TIMEOUT) {
    return new Promise((resolve, reject) => {
      const id = `msg_${++this._counter}_${Date.now()}`;
      const timer = setTimeout(() => {
        this._pendingRequests.delete(id);
        reject(new Error(`Request timeout: ${type}`));
      }, timeout);

      this._pendingRequests.set(id, { resolve, reject, timer });

      this._send({
        id,
        type,
        payload,
        direction: 'request',
        source: 'wallet-savior',
      });
    });
  }

  /** 단방향 메시지 전송 */
  send(type, payload = {}) {
    this._send({
      id: `msg_${++this._counter}_${Date.now()}`,
      type,
      payload,
      direction: 'push',
      source: 'wallet-savior',
    });
  }

  /** 내부 전송 */
  _send(message) {
    if (!this._target) {
      throw new Error('Target window not set');
    }
    this._target.postMessage(message, this._targetOrigin);
  }

  /** 수신 메시지 처리 */
  _onMessage(event) {
    // origin 검증
    if (!this.isOriginAllowed(event.origin)) {
      return;
    }

    const data = event.data;
    if (!data || data.source !== 'wallet-savior') return;

    // 응답 메시지 처리
    if (data.direction === 'response') {
      const pending = this._pendingRequests.get(data.id);
      if (pending) {
        clearTimeout(pending.timer);
        this._pendingRequests.delete(data.id);
        if (data.error) {
          pending.reject(new Error(data.error));
        } else {
          pending.resolve(data.payload);
        }
      }
      return;
    }

    // 요청 메시지 처리
    if (data.direction === 'request') {
      const handler = this._handlers.get(data.type);
      if (handler) {
        Promise.resolve()
          .then(() => handler(data.payload, event))
          .then((result) => {
            const response = {
              id: data.id,
              type: data.type,
              payload: result,
              direction: 'response',
              source: 'wallet-savior',
            };
            // SECURITY: Never post to '*'. For sandboxed iframes (origin 'null'),
            // use the configured target origin.
            const replyOrigin = event.origin === 'null'
              ? this._targetOrigin
              : event.origin;
            event.source.postMessage(response, replyOrigin);
          })
          .catch((err) => {
            const response = {
              id: data.id,
              type: data.type,
              error: err.message,
              direction: 'response',
              source: 'wallet-savior',
            };
            const replyOrigin = event.origin === 'null'
              ? this._targetOrigin
              : event.origin;
            event.source.postMessage(response, replyOrigin);
          });
      }
      return;
    }

    // push 메시지 처리
    if (data.direction === 'push') {
      const handler = this._handlers.get(data.type);
      if (handler) {
        handler(data.payload, event);
      }
    }
  }
}

export default MessageBridge;
