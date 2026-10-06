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
import { render, screen, act, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import App from '../App';
import LoginModal from '../components/modals/LoginModal';

vi.mock('../services/accountSync', () => ({ syncAccountData: vi.fn().mockResolvedValue([]) }));
function LocationProbe() { return <output data-testid="route">{useLocation().pathname}</output>; }

describe('앱 부팅 시 로그인 모달 자동 노출 방지', () => {
  beforeEach(() => {
    useStore.setState({ isLoginModalOpen: false, isLoggedIn: false, user: null });
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('제공자 로그인은 Google만 노출하며 이메일 로그인과 회원가입은 유지한다', () => {
    useStore.setState({ isLoginModalOpen: true });
    global.fetch = vi.fn();
    render(<LoginModal />);
    expect(screen.getByRole('button', { name: '구글로 시작하기' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /카카오|네이버/ })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '이메일', exact: true })).toBeInTheDocument();
    expect(screen.getByLabelText('비밀번호', { exact: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '회원가입' }));
    expect(screen.getByRole('tab', { name: '회원가입' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByPlaceholderText('2~20자')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '회원가입', exact: true })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /카카오|네이버/ })).not.toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
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
  it('잘못된 로그인 자격 증명은 실제 오류를 보존하며 세션 갱신을 시도하지 않는다', async () => {
    const detail = '이메일 또는 비밀번호가 올바르지 않습니다';
    global.fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ detail }), { status: 401 }));

    await expect(authService.login('synthetic@example.invalid', 'test-only')).rejects.toMatchObject({ status: 401, message: detail, data: { detail } });
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(useStore.getState().isLoginModalOpen).toBe(false);
  });

  it('프로필 직접 진입은 서버 세션 확인이 끝날 때까지 실제 인증 가드를 실행하지 않는다', async () => {
    vi.spyOn(authService, 'hasSessionMarker').mockReturnValue(true);
    let finish;
    vi.spyOn(authService, 'getProfile').mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<MemoryRouter initialEntries={['/profile']}><App /><LocationProbe /></MemoryRouter>);
    expect(screen.getByTestId('route')).toHaveTextContent('/profile');
    expect(screen.queryByText('로그인이 필요합니다')).not.toBeInTheDocument();
    await act(async () => finish({ id: 1, nickname: '합성 사용자', email: 'synthetic@example.invalid' }));
    await screen.findByRole('heading', { name: '합성 사용자' });
    expect(screen.getByTestId('route')).toHaveTextContent('/profile');
  });

  it('실패한 서버 세션 확인은 대기를 끝내고 실제 비인증 프로필 가드를 유지한다', async () => {
    vi.spyOn(authService, 'hasSessionMarker').mockReturnValue(true);
    vi.spyOn(authService, 'getProfile').mockRejectedValue(new Error('synthetic verification failure'));
    global.fetch = vi.fn().mockRejectedValue(new Error('no synthetic public fixtures'));
    render(<MemoryRouter initialEntries={['/profile']}><App /><LocationProbe /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent(/^\/$/));
    expect(useStore.getState().isLoggedIn).toBe(false);
  });
});
