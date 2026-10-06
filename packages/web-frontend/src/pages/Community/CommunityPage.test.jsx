import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import CommunityPage from './CommunityPage';

const session = vi.hoisted(() => ({ isLoggedIn: true, user: { id: 7 }, addToast: vi.fn(),
  logout: vi.fn(), openLoginModal: vi.fn() }));
vi.mock('../../stores/appStore', () => ({ default: Object.assign(() => session, { getState: () => session }) }));
vi.mock('../../components/community/RichTextEditor', () => ({ default: ({ content, onChange }) =>
  <textarea aria-label="본문" value={content} onChange={event => onChange(event.target.value)} /> }));
vi.mock('../../components/community/ProductPicker', () => ({ default: () => null }));

const post = (id, title, extra = {}) => ({ id, title, content: '본문', post_type: 'hotdeal',
  category: '마트', author_id: 7, author_nickname: '테스트 작성자', created_at: '2026-10-03T00:00:00Z',
  hot_votes: 0, not_votes: 0, comments_count: 0, views: 1, price: 1000, url: 'https://example.test/deal', ...extra });
const response = (body, status = 200) => ({ ok: status < 400, status, statusText: 'error', json: async () => body });
const page = (data, pages = 3, pinned = []) => response({ data, meta: { total_pages: pages }, pinned_posts: pinned });
const urlOf = input => new URL(input, 'http://localhost');
const listCalls = () => fetch.mock.calls.filter(([url, options]) => urlOf(url).pathname === '/api/posts' && !options?.method);
const queryOf = call => Object.fromEntries(urlOf(call[0]).searchParams);
const show = state => render(<MemoryRouter initialEntries={[{ pathname: '/community', state }]}><CommunityPage /></MemoryRouter>);

beforeEach(() => {
  session.isLoggedIn = true;
  session.user = { id: 7 };
  vi.stubGlobal('fetch', vi.fn());
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  session.addToast.mockClear(); session.logout.mockClear(); session.openLoginModal.mockClear(); });

describe('Community bounded query and canonical mutation refresh', () => {
  it('loads only the requested page with server pins and forwards category, literal search, sorting and free tags', async () => {
    fetch.mockImplementation(async input => {
      const params = urlOf(input).searchParams;
      return page([post(4, params.get('q') ? '서버 검색 결과' : `서버 페이지 ${params.get('page')}`)], 99,
        params.get('q') || params.get('post_type') === 'free' ? [] : [post(90, '서버 선정 인기글', { hot_votes: 3 })]);
    });
    show();
    await screen.findByText('서버 페이지 1');
    expect(listCalls()).toHaveLength(1); // total_pages=99 never triggers a whole-board download.
    expect(queryOf(listCalls()[0])).toEqual({ post_type: 'hotdeal', page: '1', per_page: '10', sort: 'popular', partition_pinned: 'true' });
    expect(screen.getAllByText('서버 선정 인기글')).toHaveLength(1);
    fireEvent.click(screen.getByText('다음 →'));
    await screen.findByText('서버 페이지 2');
    expect(queryOf(listCalls().at(-1)).page).toBe('2');
    fireEvent.click(screen.getByRole('button', { name: '마트', exact: true }));
    await screen.findByText('서버 페이지 1');
    expect(queryOf(listCalls().at(-1)).category).toBe('마트');
    fireEvent.change(screen.getByLabelText('게시글 검색'), { target: { value: '100%_한글' } });
    await screen.findByText('서버 검색 결과');
    expect(queryOf(listCalls().at(-1)).q).toBe('100%_한글');
    expect(screen.queryByText('서버 선정 인기글')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'comments' } });
    await waitFor(() => expect(queryOf(listCalls().at(-1)).sort).toBe('comments'));
    fireEvent.click(screen.getByText('💬 자유 게시판'));
    await screen.findByText('서버 페이지 1');
    expect(queryOf(listCalls().at(-1))).toMatchObject({ post_type: 'free', sort: 'recent', page: '1' });
    expect(queryOf(listCalls().at(-1)).q).toBeUndefined();
    fireEvent.click(screen.getByText('#질문'));
    await waitFor(() => expect(queryOf(listCalls().at(-1)).category).toBe('질문'));
  });

  it('ignores a superseded successful response even when the transport does not honor abort', async () => {
    let resolveOld;
    fetch.mockImplementation(input => urlOf(input).searchParams.get('post_type') === 'hotdeal'
      ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve(page([post(8, '현재 자유글', { post_type: 'free' })])));
    show();
    await waitFor(() => expect(listCalls()).toHaveLength(1));
    const previousSignal = listCalls()[0][1].signal;
    fireEvent.click(screen.getByText('💬 자유 게시판'));
    await screen.findByText('현재 자유글');
    await act(async () => resolveOld(page([post(1, '늦은 핫딜')], 99, [post(2, '늦은 인기글')])));
    expect(previousSignal.aborted).toBe(true);
    expect(screen.getByText('현재 자유글')).toBeInTheDocument();
    expect(screen.queryByText('늦은 핫딜')).not.toBeInTheDocument();
    expect(screen.queryByText('늦은 인기글')).not.toBeInTheDocument();
  });

  it('refreshes the same category, sort and page after successful votes/comments while a rejected vote does not refresh', async () => {
    let votes = 0;
    let phase = '전';
    fetch.mockImplementation(async (input, options) => {
      const path = urlOf(input).pathname;
      if (path === '/api/posts') return page([post(2, `목록 ${phase}`, { comments_count: phase === '댓글 후' ? 7 : 0 })]);
      if (path.endsWith('/vote')) {
        if (++votes === 1) return response({ detail: '투표 제한' }, 403);
        phase = '투표 후';
        return response({ data: { hot_votes: 5, not_votes: 0, user_vote: 'hot' } });
      }
      if (path.endsWith('/comments')) {
        if (options?.method === 'POST') {
          phase = '댓글 후';
          return response({ data: { id: 7, content: '등록 댓글' } });
        }
        return response({ data: phase === '댓글 후' ? Array.from({ length: 7 }, (_, n) => ({ id: n, content: `댓글 ${n}` })) : [] });
      }
      return response({ data: post(2, '선택 상세') });
    });
    show();
    await screen.findByText('목록 전');
    fireEvent.click(screen.getByRole('button', { name: '마트', exact: true }));
    await screen.findByText('목록 전');
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'comments' } });
    await screen.findByText('목록 전');
    fireEvent.click(screen.getByText('다음 →'));
    await screen.findByText('목록 전');
    fireEvent.click(screen.getByText('목록 전'));
    const modal = await screen.findByRole('dialog');
    const before = listCalls().length;
    fireEvent.click(within(modal).getByText('🔥 핫딜이다'));
    await waitFor(() => expect(session.addToast).toHaveBeenCalledWith('투표 제한', 'error'));
    expect(listCalls()).toHaveLength(before);
    fireEvent.click(within(modal).getByText('🔥 핫딜이다'));
    await screen.findByText('목록 투표 후');
    expect(listCalls()).toHaveLength(before + 1);
    expect(queryOf(listCalls().at(-1))).toMatchObject({ category: '마트', sort: 'comments', page: '2' });
    fireEvent.change(within(modal).getByPlaceholderText('댓글을 입력하세요...'), { target: { value: '새 댓글' } });
    fireEvent.keyDown(within(modal).getByPlaceholderText('댓글을 입력하세요...'), { key: 'Enter' });
    await screen.findByText('목록 댓글 후');
    expect(listCalls()).toHaveLength(before + 2);
    expect(queryOf(listCalls().at(-1))).toMatchObject({ category: '마트', sort: 'comments', page: '2' });
    expect(within(modal).getByText('💬 댓글 7개')).toBeInTheDocument();
  });

  it('clamps and refetches after deletion removes the last current page without downloading intermediate pages', async () => {
    let deleted = false;
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    fetch.mockImplementation(async (input, options) => {
      const url = urlOf(input);
      if (options?.method === 'DELETE') { deleted = true; return response({ data: {} }); }
      if (url.pathname.endsWith('/comments')) return response({ data: [] });
      if (url.pathname !== '/api/posts') return response({ data: post(2, '마지막 글') });
      return page(deleted && url.searchParams.get('page') === '2' ? [] : [post(2, deleted ? '남은 첫 페이지' : '마지막 글')], deleted ? 1 : 2);
    });
    show();
    await screen.findByText('마지막 글');
    fireEvent.click(screen.getByText('다음 →'));
    await screen.findByText('마지막 글');
    fireEvent.click(screen.getByText('마지막 글'));
    fireEvent.click(within(await screen.findByRole('dialog')).getByText('삭제'));
    await screen.findByText('남은 첫 페이지');
    expect(listCalls().map(call => queryOf(call).page)).toEqual(['1', '2', '2', '1']);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens an off-page deep link and preserves nonauthor permissions and honest list/comment failures with retry', async () => {
    session.isLoggedIn = false;
    session.user = { id: 7 }; // A stale identity without a session must not expose author actions.
    let listAttempts = 0;
    let commentAttempts = 0;
    fetch.mockImplementation(async input => {
      const path = urlOf(input).pathname;
      if (path === '/api/posts') return ++listAttempts === 1 ? response({}, 503) : page([post(1, '첫 페이지')], 1);
      if (path.endsWith('/comments')) return ++commentAttempts === 1 ? response({}, 503) : response({ data: [{ id: 1, content: '실제 댓글' }] });
      return response({ data: post(99, '페이지 밖 자유글', { post_type: 'free' }) });
    });
    show({ openPostId: 99 });
    const modal = await screen.findByRole('dialog');
    expect(within(modal).getByText('페이지 밖 자유글')).toBeInTheDocument();
    expect(within(modal).queryByText('수정')).not.toBeInTheDocument();
    expect(within(modal).queryByText('삭제')).not.toBeInTheDocument();
    expect(within(modal).queryByText('🔥 핫딜이다')).not.toBeInTheDocument();
    await within(modal).findByText('댓글을 불러오지 못했습니다.');
    expect(within(modal).queryByText('아직 댓글이 없습니다.')).not.toBeInTheDocument();
    fireEvent.click(within(modal).getByText('댓글 다시 시도'));
    await within(modal).findByText('실제 댓글');
    fireEvent.click(within(modal).getByLabelText('닫기'));
    await screen.findByText('⚠️ 게시글을 불러오는 데 실패했습니다');
    fireEvent.click(screen.getByText('다시 시도'));
    await screen.findByText('첫 페이지');
    expect(listCalls()).toHaveLength(2);
    expect(fetch.mock.calls.some(([input]) => urlOf(input).pathname === '/api/posts/99')).toBe(true);
  });

  it('refreshes an edited current page and requests page one after creation while preserving its category', async () => {
    let title = '작성자 글';
    fetch.mockImplementation(async (input, options) => {
      const url = urlOf(input);
      if (options?.method === 'PUT' || options?.method === 'POST') {
        title = JSON.parse(options.body).title;
        return response({ data: post(2, title) });
      }
      if (url.pathname.endsWith('/comments')) return response({ data: [] });
      if (url.pathname === '/api/posts') return page([post(2, title)]);
      return response({ data: post(2, title) });
    });
    show();
    await screen.findByText('작성자 글');
    fireEvent.click(screen.getByRole('button', { name: '마트', exact: true }));
    await screen.findByText('작성자 글');
    fireEvent.click(screen.getByText('다음 →'));
    await screen.findByText('작성자 글');
    fireEvent.click(screen.getByText('작성자 글'));
    fireEvent.click(within(await screen.findByRole('dialog')).getByText('수정'));
    fireEvent.change(screen.getByPlaceholderText('제목을 입력하세요'), { target: { value: '수정 완료 글' } });
    fireEvent.click(screen.getByRole('button', { name: '수정', exact: true }));
    await screen.findByText('수정 완료 글');
    expect(queryOf(listCalls().at(-1))).toMatchObject({ page: '2', category: '마트' });
    const edit = fetch.mock.calls.find(([, options]) => options?.method === 'PUT');
    expect(JSON.parse(edit[1].body)).toMatchObject({ title: '수정 완료 글', price: 1000, category: '마트' });
    fireEvent.click(screen.getByText('글쓰기'));
    fireEvent.change(screen.getByPlaceholderText('제목을 입력하세요'), { target: { value: '새 글' } });
    fireEvent.change(screen.getByPlaceholderText('가격 (원, 필수)'), { target: { value: '2000' } });
    fireEvent.change(screen.getByPlaceholderText('핫딜 링크 (필수)'), { target: { value: 'https://example.test/new' } });
    fireEvent.click(screen.getByRole('button', { name: '등록', exact: true }));
    await screen.findByText('새 글');
    expect(queryOf(listCalls().at(-1))).toMatchObject({ page: '1', category: '마트' });
  });
});

describe('Community server own-vote restoration', () => {
  it.each(['hot', 'not', null])('restores only the authenticated server vote %s on a cold detail and clears it after undo', async ownVote => {
    fetch.mockImplementation(async (input, options) => {
      const path = urlOf(input).pathname;
      if (path === '/api/posts') return page([], 1, [post(2, '인기글', { hot_votes: 9, not_votes: 3, user_vote: ownVote })]);
      if (path.endsWith('/comments')) return response({ data: [] });
      if (options?.method === 'POST') return response({ data: { hot_votes: 8, not_votes: 2, user_vote: null } });
      return response({ data: post(2, '인기글', { hot_votes: 9, not_votes: 3, user_vote: ownVote }) });
    });
    show();
    fireEvent.click(await screen.findByText('인기글', { exact: false }));
    const modal = await screen.findByRole('dialog');
    const hot = within(modal).getByRole('button', { name: '🔥 핫딜이다' });
    const not = within(modal).getByRole('button', { name: '❄️ 아니다' });
    expect(hot).toHaveAttribute('aria-pressed', String(ownVote === 'hot'));
    expect(not).toHaveAttribute('aria-pressed', String(ownVote === 'not'));
    if (ownVote) {
      fireEvent.click(ownVote === 'hot' ? hot : not);
      await waitFor(() => expect(hot).toHaveAttribute('aria-pressed', 'false'));
      expect(not).toHaveAttribute('aria-pressed', 'false');
      const writes = fetch.mock.calls.filter(([, options]) => options?.method === 'POST');
      expect(writes).toHaveLength(1);
      expect(JSON.parse(writes[0][1].body)).toEqual({ vote_type: ownVote });
    } else expect(fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  });

  it('does not reuse a previous account vote after switching accounts or returning from logout', async () => {
    fetch.mockImplementation(async input => {
      const path = urlOf(input).pathname;
      if (path === '/api/posts') return page([post(2, '계정별 투표')], 1);
      if (path.endsWith('/comments')) return response({ data: [] });
      return response({ data: post(2, '계정별 투표', { hot_votes: 9, user_vote: 'hot' }) });
    });
    const view = show();
    fireEvent.click(await screen.findByText('계정별 투표'));
    const hot = within(await screen.findByRole('dialog')).getByRole('button', { name: '🔥 핫딜이다' });
    expect(hot).toHaveAttribute('aria-pressed', 'true');
    session.user = { id: 8 };
    view.rerender(<MemoryRouter><CommunityPage /></MemoryRouter>);
    expect(hot).toHaveAttribute('aria-pressed', 'false');
    session.isLoggedIn = false;
    view.rerender(<MemoryRouter><CommunityPage /></MemoryRouter>);
    session.isLoggedIn = true;
    session.user = { id: 7 };
    view.rerender(<MemoryRouter><CommunityPage /></MemoryRouter>);
    expect(hot).toHaveAttribute('aria-pressed', 'false');
    expect(fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  });
});

describe('355 Community expired session common refresh', () => {
  const deferred = () => {
    let resolve;
    const promise = new Promise(yes => { resolve = yes; });
    return { promise, resolve };
  };
  const prepare = async kind => {
    if (kind === 'create') {
      fireEvent.click(screen.getByText('💬 자유 게시판'));
      await screen.findByText('작성자 글');
      fireEvent.click(screen.getByText('글쓰기'));
    } else {
      fireEvent.click(screen.getByText('작성자 글'));
      const dialog = await screen.findByRole('dialog');
      if (kind === 'edit') fireEvent.click(within(dialog).getByText('수정'));
    }
    if (kind === 'create' || kind === 'edit') {
      fireEvent.change(screen.getByPlaceholderText('제목을 입력하세요'), { target: { value: '보존할 제목' } });
      fireEvent.change(screen.getByLabelText('본문'), { target: { value: '보존할 본문' } });
      const submit = screen.getByRole('button', { name: kind === 'edit' ? '수정' : '등록', exact: true });
      return () => fireEvent.click(submit);
    }
    const dialog = screen.getByRole('dialog');
    if (kind === 'comment') {
      const input = within(dialog).getByPlaceholderText('댓글을 입력하세요...');
      fireEvent.change(input, { target: { value: '보존할 댓글' } });
      return () => fireEvent.keyDown(input, { key: 'Enter' });
    }
    return () => fireEvent.click(within(dialog).getByText(kind === 'vote' ? '🔥 핫딜이다' : '삭제'));
  };
  const installTransport = refresh => {
    let attempts = 0, applied = 0;
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    fetch.mockImplementation(async (input, options) => {
      const path = urlOf(input).pathname;
      if (path === '/api/auth/refresh') return refresh.promise;
      if (options?.method && options.method !== 'GET') {
        if (++attempts === 1) return response({ detail: '만료된 세션' }, 401);
        applied++;
        return response({ data: { ...post(2, '보존할 제목'), hot_votes: 1, user_vote: 'hot' } });
      }
      if (path === '/api/posts') return page([post(2, applied ? '보존할 제목' : '작성자 글')]);
      if (path.endsWith('/comments')) return response({ data: [] });
      return response({ data: post(2, '작성자 글') });
    });
    return { attempts: () => attempts, applied: () => applied };
  };

  it.each(['create', 'edit', 'comment', 'vote', 'delete'])('refreshes an expired %s session once and applies exactly one mutation despite repeated input', async kind => {
    const refresh = deferred();
    const transport = installTransport(refresh);
    show();
    await screen.findByText('작성자 글');
    const trigger = await prepare(kind);
    const before = listCalls().length;
    trigger();
    await waitFor(() => expect(fetch.mock.calls.filter(([url]) => urlOf(url).pathname === '/api/auth/refresh')).toHaveLength(1));
    trigger();
    expect(transport.attempts()).toBe(1);
    await act(async () => refresh.resolve(response({ data: {} })));
    await waitFor(() => expect(transport.applied()).toBe(1));
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(before));
    const mutations = fetch.mock.calls.filter(([url, options]) => options?.method && options.method !== 'GET' && urlOf(url).pathname !== '/api/auth/refresh');
    expect(mutations).toHaveLength(2); // Initial rejected request + one authorized replay, not two writes.
    expect(mutations[1][0]).toBe(mutations[0][0]);
    expect(mutations[1][1]).toMatchObject({ method: mutations[0][1].method, credentials: 'include' });
    expect(mutations[1][1].body).toBe(mutations[0][1].body);
    expect(session.logout).not.toHaveBeenCalled();
    expect(session.openLoginModal).not.toHaveBeenCalled();
  });

  it.each(['create', 'comment'])('retains %s draft when refresh also fails without replaying the mutation', async kind => {
    const refresh = deferred();
    const transport = installTransport(refresh);
    show();
    await screen.findByText('작성자 글');
    const trigger = await prepare(kind);
    const before = listCalls().length;
    trigger();
    await waitFor(() => expect(fetch.mock.calls.filter(([url]) => urlOf(url).pathname === '/api/auth/refresh')).toHaveLength(1));
    await act(async () => refresh.resolve(response({ detail: '갱신 불가' }, 401)));
    await waitFor(() => expect(session.addToast).toHaveBeenCalledWith('로그인이 필요합니다.', 'error'));
    expect(transport.attempts()).toBe(1);
    expect(transport.applied()).toBe(0);
    expect(listCalls()).toHaveLength(before);
    if (kind === 'create') {
      expect(screen.getByPlaceholderText('제목을 입력하세요')).toHaveValue('보존할 제목');
      expect(screen.getByLabelText('본문')).toHaveValue('보존할 본문');
    } else expect(screen.getByPlaceholderText('댓글을 입력하세요...')).toHaveValue('보존할 댓글');
    expect(session.logout).toHaveBeenCalledTimes(1);
    expect(session.openLoginModal).toHaveBeenCalledTimes(1);
  });
});
