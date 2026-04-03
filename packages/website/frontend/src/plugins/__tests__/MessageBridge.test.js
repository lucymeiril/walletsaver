/**
 * MessageBridge 테스트 — postMessage 보안 및 통신
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MessageBridge } from '../sdk/MessageBridge.js';

describe('MessageBridge', () => {
  let bridge;
  let mockTarget;

  beforeEach(() => {
    mockTarget = { postMessage: vi.fn() };
    bridge = new MessageBridge({
      targetWindow: mockTarget,
      targetOrigin: '*',
      allowedOrigins: [],
    });
  });

  afterEach(() => {
    bridge.disconnect();
  });

  it('connect()로 메시지 리스너 등록', () => {
    const spy = vi.spyOn(window, 'addEventListener');
    bridge.connect();
    expect(spy).toHaveBeenCalledWith('message', expect.any(Function));
    spy.mockRestore();
  });

  it('disconnect()로 리스너 해제', () => {
    bridge.connect();
    const spy = vi.spyOn(window, 'removeEventListener');
    bridge.disconnect();
    expect(spy).toHaveBeenCalledWith('message', expect.any(Function));
    spy.mockRestore();
  });

  it('disconnect() 시 대기 중인 요청 reject', async () => {
    bridge.connect();
    const promise = bridge.request('test', {}, 10000);
    bridge.disconnect();
    await expect(promise).rejects.toThrow('Bridge disconnected');
  });

  it('origin 검증 — allowedOrigins 비어있으면 모두 허용', () => {
    expect(bridge.isOriginAllowed('http://evil.com')).toBe(true);
  });

  it('origin 검증 — 허용된 origin만 통과', () => {
    const restrictedBridge = new MessageBridge({
      targetWindow: mockTarget,
      targetOrigin: '*',
      allowedOrigins: ['http://localhost:3000'],
    });
    expect(restrictedBridge.isOriginAllowed('http://localhost:3000')).toBe(true);
    expect(restrictedBridge.isOriginAllowed('http://evil.com')).toBe(false);
    restrictedBridge.disconnect();
  });

  it('send()로 단방향 메시지 전송', () => {
    bridge.send('testType', { data: 123 });
    expect(mockTarget.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'testType',
        payload: { data: 123 },
        direction: 'push',
        source: 'wallet-savior',
      }),
      '*'
    );
  });

  it('target 없으면 send 시 에러 발생', () => {
    const noBridge = new MessageBridge({
      targetWindow: null,
      targetOrigin: '*',
      allowedOrigins: [],
    });
    expect(() => noBridge.send('test')).toThrow('Target window not set');
  });

  it('on()/off()로 핸들러 등록/해제', () => {
    const handler = vi.fn();
    bridge.on('test', handler);
    bridge.off('test');
    // 내부 핸들러 맵에서 제거 확인
    expect(bridge._handlers.has('test')).toBe(false);
  });

  it('request()에 타임아웃 설정', async () => {
    bridge.connect();
    const promise = bridge.request('slow', {}, 50);
    await expect(promise).rejects.toThrow('Request timeout: slow');
  });

  it('수신 메시지 — source가 wallet-savior가 아니면 무시', () => {
    const handler = vi.fn();
    bridge.on('test', handler);
    bridge.connect();

    const event = new MessageEvent('message', {
      data: { type: 'test', direction: 'push', source: 'other' },
      origin: 'http://localhost',
    });
    window.dispatchEvent(event);
    expect(handler).not.toHaveBeenCalled();
  });

  it('수신 push 메시지 처리', () => {
    const handler = vi.fn();
    bridge.on('greet', handler);
    bridge.connect();

    const event = new MessageEvent('message', {
      data: {
        id: 'msg_1',
        type: 'greet',
        payload: { msg: 'hello' },
        direction: 'push',
        source: 'wallet-savior',
      },
      origin: 'http://localhost',
    });
    window.dispatchEvent(event);
    expect(handler).toHaveBeenCalledWith({ msg: 'hello' }, expect.any(Object));
  });

  it('수신 응답 메시지로 request resolve', async () => {
    bridge.connect();
    const promise = bridge.request('getData', { id: 1 }, 2000);

    // 매칭되는 응답 전송
    const sentMsg = mockTarget.postMessage.mock.calls[0][0];
    const responseEvent = new MessageEvent('message', {
      data: {
        id: sentMsg.id,
        type: 'getData',
        payload: { result: 'ok' },
        direction: 'response',
        source: 'wallet-savior',
      },
      origin: 'http://localhost',
    });
    window.dispatchEvent(responseEvent);

    const result = await promise;
    expect(result).toEqual({ result: 'ok' });
  });

  it('수신 응답 에러로 request reject', async () => {
    bridge.connect();
    const promise = bridge.request('fail', {}, 2000);

    const sentMsg = mockTarget.postMessage.mock.calls[0][0];
    const responseEvent = new MessageEvent('message', {
      data: {
        id: sentMsg.id,
        type: 'fail',
        error: '서버 오류',
        direction: 'response',
        source: 'wallet-savior',
      },
      origin: 'http://localhost',
    });
    window.dispatchEvent(responseEvent);

    await expect(promise).rejects.toThrow('서버 오류');
  });
});
