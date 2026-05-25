/**
 * 회귀 테스트: 메인 페이지 진입 시 로그인 모달이 자동 노출되지 않아야 한다.
 *
 * 사용자 헌법: "최소노력/복잡지않게", "초심자도 이용하기 쉽게"
 * 로그인은 사용자 액션(글쓰기/저장/북마크/댓글) 시점에만 트리거되어야 한다.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import useStore from '../stores/appStore';
import { api } from '../services/api';
import { authService } from '../services/authService';

describe('앱 부팅 시 로그인 모달 자동 노출 방지', () => {
  beforeEach(() => {
    useStore.setState({ isLoginModalOpen: false, isLoggedIn: false, user: null });
    vi.restoreAllMocks();
  });

  it('인증되지 않은 상태에서 부팅 시 getProfile 401이 로그인 모달을 열지 않는다', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 })); // refresh 실패

    await expect(authService.getProfile({ silent: true })).rejects.toMatchObject({ status: 401 });

    expect(useStore.getState().isLoginModalOpen).toBe(false);
  });

  it('silent 옵션 없는 API 호출(사용자 액션)에서 401은 로그인 모달을 연다', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 })); // refresh 실패

    await expect(api.post('/api/wishlist', { product_id: 1 })).rejects.toMatchObject({ status: 401 });

    expect(useStore.getState().isLoginModalOpen).toBe(true);
  });
});
