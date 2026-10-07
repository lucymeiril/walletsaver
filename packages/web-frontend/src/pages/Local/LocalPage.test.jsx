import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LocalPage from './LocalPage';
import GasDetailContent from './components/GasDetailContent';
import NaverPlaceDetailContent from './components/NaverPlaceDetailContent';
import { distanceKm, sortItems, itemsWithinRadius } from './utils';

const store = vi.hoisted(() => ({ addToast: vi.fn(), setSavedLocation: vi.fn(), savedLocation: null }));
vi.mock('../../stores/appStore', () => ({
  default: () => store,
}));

function jsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(payload),
  });
}

function streamResponse(events) {
  const bytes = new TextEncoder().encode(
    events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(''),
  );
  let sent = false;
  return Promise.resolve({
    ok: true,
    body: {
      getReader: () => ({
        read: async () => {
          if (sent) return { done: true, value: undefined };
          sent = true;
          return { done: false, value: bytes };
        },
        releaseLock: vi.fn(),
      }),
    },
  });
}

describe('LocalPage browser-search consent', () => {
  beforeEach(() => {
    store.savedLocation = null;
    store.addToast.mockReset();
    store.setSavedLocation.mockReset().mockImplementation(location => { store.savedLocation = location; });
    global.fetch = vi.fn((url) => {
      const href = String(url);
      if (href.includes('/api/local/geocode')) {
        return jsonResponse({
          success: true,
          data: { name: '강남역', lat: 37.4979, lng: 127.0276 },
        });
      }
      if (href.includes('/api/local/area-explore-stream')) {
        return streamResponse([{ name: '음식', items: [], source: 'unavailable' }, { done: true }]);
      }
      if (href.includes('/api/gas/nearby')) return jsonResponse({ data: [], message: '현재 반경에 가격 정보가 없습니다' });
      return jsonResponse({ success: true, data: { items: [] } });
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    delete window.navigator.geolocation;
  });

  it('searches only after opt-in and never embeds the blocked Naver iframe', async () => {
    const user = userEvent.setup();
    render(<LocalPage />);

    const consent = screen.getByRole('checkbox', {
      name: /네이버 공개 페이지 브라우저 검색 사용/,
    });
    expect(consent).not.toBeChecked();
    expect(screen.queryByTitle('네이버 지도')).not.toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/위치를 입력하세요/), '강남역');
    await user.click(screen.getAllByRole('button').find(button => button.querySelector('svg')));

    await waitFor(() => {
      const areaCall = global.fetch.mock.calls.find(([url]) =>
        String(url).includes('/api/local/area-explore-stream'),
      );
      expect(areaCall).toBeTruthy();
      expect(String(areaCall[0])).toContain('browser_search=false');
    });

    await user.click(consent);

    await waitFor(() => {
      const areaCalls = global.fetch.mock.calls.filter(([url]) =>
        String(url).includes('/api/local/area-explore-stream'),
      );
      expect(areaCalls.length).toBeGreaterThanOrEqual(2);
      expect(String(areaCalls.at(-1)[0])).toContain('browser_search=true');
    });
  });

  it.each([
    [{ source: 'unavailable', items: [] }, false],
    [{ items: [] }, false],
    [{ source: 'naver', items: [] }, true],
  ])('distinguishes unavailable direct place capture from an observed empty list (%j)', async (result, observedEmpty) => {
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => String(url).includes('/api/local/naver-search')
      ? jsonResponse({ success: true, data: result }) : previous(url, ...args));
    const user = userEvent.setup(); render(<LocalPage />);
    await user.click(screen.getByRole('checkbox', { name: /네이버 공개 페이지 브라우저 검색 사용/ }));
    const location = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(location, '강남역'); fireEvent.submit(location.closest('form'));
    const query = await screen.findByPlaceholderText(/주변 검색/);
    await user.type(query, '카페'); fireEvent.submit(query.closest('form'));
    const status = await screen.findByRole('status', { name: '장소 검색 상태' });
    await waitFor(() => expect(status).toHaveTextContent(observedEmpty ? '검색 결과가 없습니다' : '장소 검색 결과를 확인할 수 없습니다'));
    expect(store.addToast.mock.calls.some(([message]) => message === '검색 결과 없음')).toBe(observedEmpty);
    if (observedEmpty) expect(screen.getByText('0건의 결과')).toBeInTheDocument();
    else expect(screen.queryByText('0건의 결과')).not.toBeInTheDocument();
    const calls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/api/local/naver-search'));
    expect(calls).toHaveLength(1);
    expect(new URL(calls[0][0], 'http://localhost').searchParams.get('browser_search')).toBe('true');
  });

  it('keeps disabled direct place search unqueried instead of reporting zero results', async () => {
    const user = userEvent.setup(); render(<LocalPage />);
    const location = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(location, '강남역'); fireEvent.submit(location.closest('form'));
    const query = await screen.findByPlaceholderText(/주변 검색/);
    await user.type(query, '카페'); fireEvent.submit(query.closest('form'));
    expect(await screen.findByRole('status', { name: '장소 검색 상태' })).toHaveTextContent('장소 검색이 꺼져 있습니다');
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/api/local/naver-search'))).toBe(false);
    expect(store.addToast.mock.calls.some(([message]) => message === '검색 결과 없음')).toBe(false);
    expect(screen.queryByText('0건의 결과')).not.toBeInTheDocument();
  });

  it.each([
    [[{ name: '음식', source: 'unavailable', items: [] }, { done: true }], '결과 미확인'],
    [[{ name: '음식', source: 'naver', items: [] }, { done: true }], '조회됨'],
    [[{ done: true }], '조회 대기'],
  ])('retains the actual place source state in the area summary (%j)', async (events, label) => {
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => String(url).includes('/api/local/area-explore-stream')
      ? streamResponse(events) : previous(url, ...args));
    const user = userEvent.setup(); render(<LocalPage />);
    await user.click(screen.getByRole('checkbox', { name: /네이버 공개 페이지 브라우저 검색 사용/ }));
    const location = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(location, '강남역'); fireEvent.submit(location.closest('form'));
    expect(await screen.findByText(label, { exact: true })).toBeInTheDocument();
    expect(Boolean(screen.queryByText(/브라우저 검색 결과가 없습니다/))).toBe(label === '조회됨');
    expect(Boolean(screen.queryByText('장소 결과', { exact: true }))).toBe(label !== '조회됨');
  });

  it('keeps a failed area response unavailable instead of reporting an empty place list', async () => {
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => String(url).includes('/api/local/area-explore-stream')
      ? Promise.resolve({ ok: false }) : previous(url, ...args));
    const user = userEvent.setup(); render(<LocalPage />);
    await user.click(screen.getByRole('checkbox', { name: /네이버 공개 페이지 브라우저 검색 사용/ }));
    const location = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(location, '강남역'); fireEvent.submit(location.closest('form'));
    expect(await screen.findByText('결과 미확인', { exact: true })).toBeInTheDocument();
    expect(screen.queryByText(/브라우저 검색 결과가 없습니다/)).not.toBeInTheDocument();
  });

  it.each([
    ['subcategory', 'done'],
    ['items', 'done'],
    ['detail', 'done'],
    ['items', 'eof'],
    ['items', 'error'],
  ])('keeps a selected %s when background area capture ends with %s', async (selection, ending) => {
    let finishRead;
    const previous = global.fetch.getMockImplementation();
    const items = [
      { name: '먼저 도착한 카페', category: '카페', x: 127.0276, y: 37.4979,
        address: '서울 강남구', menus: [{ name: '커피', price: 2000 }] },
      { name: '먼저 도착한 음식점', category: '음식점', x: 127.0276, y: 37.4979 },
    ];
    global.fetch.mockImplementation((url, ...args) => {
      if (!String(url).includes('/api/local/area-explore-stream')) return previous(url, ...args);
      let first = true;
      return Promise.resolve({ ok: true, body: { getReader: () => ({
        read: () => {
          if (first) {
            first = false;
            return Promise.resolve({ done: false, value: new TextEncoder().encode(
              `data: ${JSON.stringify({ name: '카페', source: 'naver', items })}\n\n`,
            ) });
          }
          return new Promise((resolve, reject) => { finishRead = { resolve, reject }; });
        },
        releaseLock: vi.fn(),
      }) } });
    });
    const user = userEvent.setup(); render(<LocalPage />);
    await user.click(screen.getByRole('checkbox', { name: /네이버 공개 페이지 브라우저 검색 사용/ }));
    const location = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(location, '강남역'); fireEvent.submit(location.closest('form'));
    await user.click(await screen.findByRole('button', { name: name => name.includes('카페') && name.includes('2건') }));
    const all = screen.getByRole('button', { name: '📋 전체 보기 (2)' });
    if (selection !== 'subcategory') {
      await user.click(all);
      if (selection === 'detail') await user.click(screen.getByText('먼저 도착한 카페'));
    }
    await waitFor(() => expect(finishRead).toBeTruthy());
    await act(async () => {
      if (ending === 'error') finishRead.reject(new Error('late stream failure'));
      else if (ending === 'eof') finishRead.resolve({ done: true });
      else finishRead.resolve({ done: false, value: new TextEncoder().encode('data: {"done":true}\n\n') });
    });
    if (selection === 'subcategory') expect(screen.getByRole('button', { name: '📋 전체 보기 (2)' })).toBeVisible();
    else {
      expect(screen.getByText('2건의 결과')).toBeVisible();
      expect(screen.getAllByText('먼저 도착한 카페').length).toBeGreaterThan(0);
      if (selection === 'detail') expect(screen.getByRole('dialog', { name: '📍 가게 상세 정보' })).toBeVisible();
    }
    expect(global.fetch.mock.calls.filter(([url]) => String(url).includes('/api/local/area-explore-stream'))).toHaveLength(1);
    expect(store.addToast.mock.calls.some(([message]) => message.includes('주변 탐색에 실패했습니다'))).toBe(ending === 'error');
  });

  it('ignores a deferred direct place response after a manual fuel region supersedes it', async () => {
    let resolvePlace, resolveFuel, directSignal;
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => {
      const parsed = new URL(url, 'http://localhost');
      if (parsed.pathname === '/api/local/naver-search') {
        directSignal = options.signal;
        return new Promise(resolve => { resolvePlace = resolve; });
      }
      if (parsed.pathname === '/api/gas/nearby' && parsed.searchParams.has('sido')) {
        return new Promise(resolve => { resolveFuel = resolve; });
      }
      return previous(url, options);
    });
    const user = userEvent.setup(); render(<LocalPage />);
    await user.click(screen.getByRole('checkbox', { name: /네이버 공개 페이지 브라우저 검색 사용/ }));
    const location = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(location, '강남역'); fireEvent.submit(location.closest('form'));
    const query = await screen.findByPlaceholderText(/주변 검색/);
    await user.type(query, '카페'); fireEvent.submit(query.closest('form'));
    await waitFor(() => expect(resolvePlace).toBeTypeOf('function'));

    await user.type(screen.getByRole('textbox', { name: '시/도' }), '서울특별시');
    await user.type(screen.getByRole('textbox', { name: '시/군/구' }), '종로구');
    await user.click(screen.getByRole('button', { name: '지역 가격 조회' }));
    expect(directSignal.aborted).toBe(true);
    await act(async () => {
      resolvePlace(await jsonResponse({ success: true, data: { source: 'naver',
        items: [{ name: '늦은 카페', x: 127.0276, y: 37.4979 }] } }));
    });
    expect(screen.queryByPlaceholderText(/주변 검색/)).not.toBeInTheDocument();
    expect(screen.queryByText('1건', { exact: true })).not.toBeInTheDocument();
    expect(store.addToast.mock.calls.some(([message]) => message.includes('카페') && message.includes('1건'))).toBe(false);
    expect(screen.getByText('검색 중...', { exact: true })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '선택한 위치를 네이버 지도에서 확인' })).toHaveAttribute('href',
      `https://map.naver.com/p/search/${encodeURIComponent('서울특별시 종로구')}`);

    await act(async () => {
      resolveFuel(await jsonResponse({ data: [{ station_code: 'region', name: '새 지역 주유소',
        gasoline: 1700, lat: null, lng: null, source: 'opinet', updated_at: '2026-10-01T07:41:00' }] }));
    });
    await user.click(await screen.findByRole('button', { name: name => name.includes('주유소') && name.includes('(') }));
    expect(screen.getByText('새 지역 주유소')).toBeInTheDocument();
    expect(screen.queryByText('늦은 카페')).not.toBeInTheDocument();
    expect(screen.getByText('거리 미확인')).toBeInTheDocument();
    expect(store.savedLocation).toEqual({ sido: '서울특별시', sigungu: '종로구',
      locationName: '서울특별시 종로구', fuelType: 'gasoline' });
  });

  it('keeps a completed manual location when an older GPS callback arrives', async () => {
    let onPosition;
    Object.defineProperty(navigator, 'geolocation', { configurable: true,
      value: { getCurrentPosition: vi.fn(callback => { onPosition = callback; }) } });
    const user = userEvent.setup();
    render(<LocalPage />);
    await user.click(screen.getByRole('button', { name: /현위치/ }));
    const input = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(input, '강남역');
    fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/api/gas/nearby'))).toBe(true));
    await act(async () => { await onPosition({ coords: { latitude: 35.1, longitude: 129.1 } }); });
    const fuelCalls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/api/gas/nearby'));
    expect(new URL(fuelCalls.at(-1)[0], 'http://localhost').searchParams.get('lat')).toBe('37.4979');
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('35.1'))).toBe(false);
  });

  it('ignores stale reverse geocoding after a newer manual selection', async () => {
    let onPosition, resolveReverse;
    Object.defineProperty(navigator, 'geolocation', { configurable: true,
      value: { getCurrentPosition: vi.fn(callback => { onPosition = callback; }) } });
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => new URL(url, 'http://localhost').searchParams.get('query') === '35.1,129.1'
      ? new Promise(resolve => { resolveReverse = resolve; }) : previous(url, ...args));
    const user = userEvent.setup();
    render(<LocalPage />);
    await user.click(screen.getByRole('button', { name: /현위치/ }));
    let pending;
    act(() => { pending = onPosition({ coords: { latitude: 35.1, longitude: 129.1 } }); });
    const input = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(input, '강남역');
    fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/api/gas/nearby'))).toBe(true));
    await act(async () => {
      resolveReverse(await jsonResponse({ success: true, data: { name: '늦은 GPS', lat: 35.1, lng: 129.1 } }));
      await pending;
    });
    expect(screen.queryByText('늦은 GPS')).not.toBeInTheDocument();
    const last = global.fetch.mock.calls.filter(([url]) => String(url).includes('/api/gas/nearby')).at(-1);
    expect(new URL(last[0], 'http://localhost').searchParams.get('lat')).toBe('37.4979');
  });

  it('sends the chosen radius to the fuel API and refreshes filtered stations', async () => {
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => {
      if (!String(url).includes('/api/gas/nearby')) return previous(url, ...args);
      const radius = Number(new URL(url, 'http://localhost').searchParams.get('radius'));
      const stations = [{ station_code: 'near', name: '가까운 주유소', gasoline: 1600, lat: 37.4979, lng: 127.0276 }];
      if (radius > 1000) stations.push({ station_code: 'far', name: '먼 주유소', gasoline: 1500, lat: 37.5179, lng: 127.0276 });
      return jsonResponse({ data: stations });
    });
    const user = userEvent.setup();
    render(<LocalPage />);
    const input = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(input, '강남역'); fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('radius=3000'))).toBe(true));
    await user.click(screen.getByRole('button', { name: '1km' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('radius=1000'))).toBe(true));
    await waitFor(() => expect(screen.getByRole('button', { name: name => name.includes('주유소') && name.includes('(') })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: name => name.includes('주유소') && name.includes('(') }));
    expect(screen.getByText('가까운 주유소')).toBeInTheDocument();
    expect(screen.queryByText('먼 주유소')).not.toBeInTheDocument();
  });

  it('shows missing fuel snapshot failure explicitly without fabricating stations', async () => {
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => String(url).includes('/api/gas/nearby')
      ? Promise.resolve({ ok: false, json: async () => ({ detail: '오피넷 snapshot을 사용할 수 없습니다' }) })
      : previous(url, ...args));
    const user = userEvent.setup(); render(<LocalPage />);
    const input = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(input, '강남역'); fireEvent.submit(input.closest('form'));
    expect(await screen.findByRole('status')).toHaveTextContent('오피넷 snapshot을 사용할 수 없습니다');
    expect(screen.queryByText('주유소')).not.toBeInTheDocument();
  });

  it('keeps explicit distance units and unknown fuel/service facts honest in station detail', () => {
    render(<GasDetailContent station={{ name: '셀프라는 이름', is_self: false, distance: 150,
      gasoline: 1600, source: 'opinet', updated_at: '2026-08-25T09:00:00' }} onFocusMap={vi.fn()} />);
    expect(screen.getByText('탐색 위치에서 약 150.0km', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('일반 주유', { exact: false })).toBeInTheDocument();
    expect(screen.getAllByText('가격 미확인')).toHaveLength(3);
    expect(screen.queryByText('취급 안 함')).not.toBeInTheDocument();
    expect(screen.getByText('가격 관측 2026-08-25T09:00', { exact: false })).toBeInTheDocument();
  });

  it('sorts zero-distance and explicit metre values correctly while keeping missing distances last', () => {
    expect(distanceKm('250m')).toBe(0.25);
    expect(distanceKm(150)).toBe(150);
    const items = [{ id: 'unknown' }, { id: 'metres', distance: '250m' }, { id: 'zero', distance: '0m' }];
    expect(sortItems(items, 'distance', 'asc').map(item => item.id)).toEqual(['zero', 'metres', 'unknown']);
    expect(sortItems(items, 'distance', 'desc').map(item => item.id)).toEqual(['metres', 'zero', 'unknown']);
  });

  it('renders coordinate-derived place detail distance in rounded km without inventing prices', () => {
    const [place] = itemsWithinRadius([{ name: '국립어린이청소년도서관',
      x: '127.0296909', y: '37.5009712', distance: '8594.44',
      url: 'https://map.naver.com/p/entry/place/11797439', rating: null, menu_info: null,
    }], 37.497952, 127.027619, 3000);
    render(<NaverPlaceDetailContent place={place} onFocusMap={vi.fn()} />);
    expect(screen.getByText('📏 0.4km')).toBeInTheDocument();
    expect(screen.queryByText(/8594|0\.382/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /네이버 지도에서 보기/ })).toHaveAttribute('href', place.url);
    expect(screen.queryByText('메뉴 가격')).not.toBeInTheDocument();
    expect(screen.queryByText(/⭐/)).not.toBeInTheDocument();
  });

  it.each([
    [{ distance: '250m' }, '📏 0.3km'],
    [{ distance_m: 0, distance: '8594.44' }, '📏 0.0km'],
    [{ distance: '8594.44' }, '거리 미확인'],
    [{}, '거리 미확인'],
    [{ distance: -1, distance_m: -1 }, '거리 미확인'],
  ])('keeps explicit place detail distance units distinct from unknown provider text (%j)', (distance, label) => {
    render(<NaverPlaceDetailContent place={{ name: '장소', ...distance }} onFocusMap={vi.fn()} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    if (label === '거리 미확인') expect(screen.queryByText(/km/)).not.toBeInTheDocument();
  });

  it.each([8594.44, 0])('holds typed raw numeric place detail distance without a declared unit (%s)', distance => {
    render(<NaverPlaceDetailContent place={{ name: '장소', distance }} onFocusMap={vi.fn()} />);
    expect(screen.getByText('거리 미확인')).toBeInTheDocument();
    expect(screen.queryByText(/km/)).not.toBeInTheDocument();
  });

  it.each([4.5, 0])('labels a known place detail rating as a score rather than a review count (%s)', rating => {
    render(<NaverPlaceDetailContent place={{ name: '장소', rating, review_count: 99 }} onFocusMap={vi.fn()} />);
    expect(screen.getByText(`⭐ 평점 ${rating}`)).toBeInTheDocument();
    expect(screen.queryByText(/리뷰.*개/)).not.toBeInTheDocument();
  });

  it('keeps unknown or invalid place detail scores unconfirmed despite a known review count', () => {
    const { rerender } = render(<NaverPlaceDetailContent place={{ name: '장소' }} onFocusMap={vi.fn()} />);
    for (const rating of [null, undefined, '4.5', NaN, Infinity, -1, 99]) {
      rerender(<NaverPlaceDetailContent place={{ name: '장소', rating, review_count: 99 }} onFocusMap={vi.fn()} />);
      expect(screen.queryByText(/⭐|평점|리뷰.*개/)).not.toBeInTheDocument();
    }
  });

  it('467 distinguishes source rows outside the chosen region from a genuine empty provider receipt', async () => {
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => String(url).includes('/api/local/area-explore-stream')
      ? streamResponse([{name:'음식',location_name:'강남역',source:'naver',items:[{name:'시청 원문',x:'126.9788852',y:'37.5648060',distance:'201.61'}, {name:'좌표 없는 원문',address:'강남역 원문 위치',distance:'100m'}]}, {done:true}])
      : previous(url, ...args));
    const user = userEvent.setup(); render(<LocalPage />);
    await user.click(screen.getByRole('checkbox', {name:/네이버 공개 페이지 브라우저 검색 사용/}));
    const location = screen.getByPlaceholderText(/위치를 입력하세요/);
    await user.type(location, '강남역'); fireEvent.submit(location.closest('form'));
    await screen.findByText(/출처 결과 2건을 받았으나 선택한 위치·반경/);
    expect(screen.queryByText('브라우저 검색 결과가 없습니다. 검색어를 바꿔 다시 시도해 주세요.')).not.toBeInTheDocument();
    expect(screen.getByText('좌표·거리·반경 미확인')).toBeInTheDocument();
    await user.click(screen.getByText('음식 · 원문 결과 1건'));
    expect(await screen.findByText('좌표 없는 원문')).toBeInTheDocument();
    expect(screen.queryByText('시청 원문')).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.filter(([url]) => String(url).includes('/api/local/area-explore-stream'))).toHaveLength(1);
  });

  it('filters supplied WGS84 place positions without inventing coordinates for unlocated results', () => {
    const items = [{ id: 'near', y: '37.5', x: '127' }, { id: 'far', y: 37.52, x: 127 },
      { id: 'unknown', distance: '100m' }, { id: 'unconverted', y: 200000, x: 500000 }];
    expect(itemsWithinRadius(items, 37.5, 127, 1000).map(item => item.id)).toEqual(['near']);
    expect(itemsWithinRadius(items, 37.5, 127, 3000).map(item => item.id)).toEqual(['near', 'far']);
    expect(itemsWithinRadius(items, 37.5, 127, 1000)[0].distance_m).toBe(0);
    expect(items[0]).not.toHaveProperty('distance_m');
  });

  it('queries an exact manual region and fuel without a provider, radius or guessed distance', async () => {
    global.fetch.mockImplementation(url => {
      const params = new URL(url, 'http://localhost').searchParams;
      return jsonResponse({ data: [{ station_code: 'unlocated', name: '위치 미확인 지역 주유소',
        address: '서울특별시 강서구', lat: null, lng: null, gasoline: 1700, diesel: 1500,
        premium: null, lpg: null, self_service: false, source: 'opinet',
        updated_at: params.get('fuel_type') === 'diesel' ? '2026-09-02T09:00:00' : '2026-08-25T09:00:00',
        price_observed_at: { gasoline: '2026-08-25T09:00:00', diesel: '2026-09-02T09:00:00' } }] });
    });
    const user = userEvent.setup(); render(<LocalPage />);
    await user.type(screen.getByRole('textbox', { name: '시/도' }), '서울특별시');
    await user.type(screen.getByRole('textbox', { name: '시/군/구' }), '강서구');
    await user.click(screen.getByRole('button', { name: '지역 가격 조회' }));
    await user.selectOptions(screen.getByRole('combobox', { name: '조회 유종' }), 'diesel');
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    for (const [url] of global.fetch.mock.calls) {
      const parsed = new URL(url, 'http://localhost');
      expect(parsed.pathname).toBe('/api/gas/nearby');
      expect(parsed.searchParams.get('sido')).toBe('서울특별시');
      expect(parsed.searchParams.get('sigungu')).toBe('강서구');
      for (const key of ['lat', 'lng', 'radius']) expect(parsed.searchParams.has(key)).toBe(false);
    }
    expect(new URL(global.fetch.mock.calls.at(-1)[0], 'http://localhost').searchParams.get('fuel_type')).toBe('diesel');
    expect(screen.queryByRole('button', { name: '1km' })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/주변 검색/)).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: name => name.includes('주유소') && name.includes('(') }));
    expect(screen.getByText('가격 관측')).toBeInTheDocument();
    await user.click(screen.getByText('위치 미확인 지역 주유소'));
    expect(screen.getAllByText('거리 미확인')).toHaveLength(2);
    expect(screen.getByText('가격 관측 2026-09-02T09:00', { exact: false })).toBeInTheDocument();
    expect(screen.getAllByText('가격 미확인')).toHaveLength(2);
  });

  it('allows a manual region to supersede pending GPS reverse geocoding through its actual button', async () => {
    let onPosition, resolveReverse;
    Object.defineProperty(navigator, 'geolocation', { configurable: true,
      value: { getCurrentPosition: vi.fn(callback => { onPosition = callback; }) } });
    const previous = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => String(url).includes('/api/local/geocode')
      ? new Promise(resolve => { resolveReverse = resolve; }) : previous(url, ...args));
    const user = userEvent.setup(); render(<LocalPage />);
    await user.click(screen.getByRole('button', { name: /현위치/ }));
    let pending;
    act(() => { pending = onPosition({ coords: { latitude: 35.1, longitude: 129.1 } }); });
    await user.type(screen.getByRole('textbox', { name: '시/도' }), '서울특별시');
    await user.type(screen.getByRole('textbox', { name: '시/군/구' }), '강서구');
    const submit = screen.getByRole('button', { name: '지역 가격 조회' });
    expect(submit).toBeEnabled(); await user.click(submit);
    expect(await screen.findByRole('status')).toBeInTheDocument();
    await act(async () => {
      resolveReverse(await jsonResponse({ success: true, data: { name: '늦은 GPS', lat: 35.1, lng: 129.1 } }));
      await pending;
    });
    expect(screen.queryByText('늦은 GPS')).not.toBeInTheDocument();
    const calls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/api/gas/nearby'));
    expect(calls).toHaveLength(1);
    const params = new URL(calls[0][0], 'http://localhost').searchParams;
    expect(params.get('sigungu')).toBe('강서구'); expect(params.has('lat')).toBe(false);
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('area-explore-stream'))).toBe(false);
  });

  it('restores the saved manual region and chosen fuel on a cold mount using fresh unlocated station observations', async () => {
    let queries = 0;
    const getCurrentPosition = vi.fn();
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: { getCurrentPosition } });
    global.fetch.mockImplementation(() => jsonResponse({ data: [{
      station_code: 'observed', name: '저장 지역 주유소', address: '서울특별시 종로구',
      lat: null, lng: null, gasoline: null, diesel: ++queries === 1 ? 1600 : 1700,
      source: 'opinet', updated_at: '2026-10-01T07:41:00',
      price_observed_at: { diesel: '2026-10-01T07:41:00' },
    }] }));
    const user = userEvent.setup();
    const mounted = render(<LocalPage />);
    await user.type(screen.getByRole('textbox', { name: '시/도' }), '서울특별시');
    await user.type(screen.getByRole('textbox', { name: '시/군/구' }), '종로구');
    await user.selectOptions(screen.getByRole('combobox', { name: '조회 유종' }), 'diesel');
    await user.click(screen.getByRole('button', { name: '지역 가격 조회' }));
    expect(await screen.findByRole('button', { name: name => name.includes('주유소') && name.includes('(') })).toBeInTheDocument();
    expect(store.savedLocation).toEqual({ sido: '서울특별시', sigungu: '종로구',
      locationName: '서울특별시 종로구', fuelType: 'diesel' });
    mounted.unmount();

    render(<LocalPage />);
    expect(screen.getByRole('textbox', { name: '시/도' })).toHaveValue('서울특별시');
    expect(screen.getByRole('textbox', { name: '시/군/구' })).toHaveValue('종로구');
    expect(screen.getByRole('combobox', { name: '조회 유종' })).toHaveValue('diesel');
    await user.click(await screen.findByRole('button', { name: name => name.includes('주유소') && name.includes('(') }));
    await user.click(screen.getByText('저장 지역 주유소'));
    expect(screen.getByText('1,700원/L')).toBeInTheDocument();
    expect(screen.queryByText('1,600원/L')).not.toBeInTheDocument();
    expect(screen.getAllByText('거리 미확인')).toHaveLength(2);
    expect(screen.getByText('가격 관측 2026-10-01T07:41', { exact: false })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(getCurrentPosition).not.toHaveBeenCalled();
    for (const [url] of global.fetch.mock.calls) {
      const parsed = new URL(url, 'http://localhost');
      expect(parsed.pathname).toBe('/api/gas/nearby');
      expect(Object.fromEntries(parsed.searchParams)).toEqual({ sido: '서울특별시',
        sigungu: '종로구', fuel_type: 'diesel', limit: '1000' });
    }
  });

  it.each([
    [{ lat: 37.5, lng: 127, sido: '서울특별시', sigungu: '종로구', fuelType: 'diesel' }, ''],
    [{ sido: '서울특별시', sigungu: '종로구' }, '서울특별시'],
    [{ sido: '서울특별시', sigungu: '종로구', fuelType: 'unproved' }, '서울특별시'],
  ])('does not auto-restore coordinate locations or an unconfirmed saved fuel (%j)', async (saved, sido) => {
    store.savedLocation = saved;
    render(<LocalPage />);
    expect(screen.getByRole('textbox', { name: '시/도' })).toHaveValue(sido);
    expect(screen.getByRole('combobox', { name: '조회 유종' })).toHaveValue('gasoline');
    await act(async () => {});
    expect(global.fetch).not.toHaveBeenCalled();
    expect(screen.queryByText('주유소 (1)')).not.toBeInTheDocument();
    const mapLink = screen.queryByRole('link', { name: '선택한 위치를 네이버 지도에서 확인' });
    if (sido) {
      expect(mapLink).toHaveAttribute('href', `https://map.naver.com/p/search/${encodeURIComponent('서울특별시 종로구')}`);
    } else {
      expect(mapLink).not.toBeInTheDocument();
    }
  });

  it.each([
    [true, '선택한 지역의 오피넷 가격 정보가 없습니다'],
    [false, '오피넷 snapshot을 사용할 수 없습니다'],
  ])('shows manual region empty or snapshot failure honestly (ok=%s)', async (ok, reason) => {
    global.fetch.mockImplementation(() => Promise.resolve({ ok, json: async () => ok
      ? { data: [], message: reason } : { detail: reason } }));
    const user = userEvent.setup(); render(<LocalPage />);
    await user.type(screen.getByRole('textbox', { name: '시/군/구' }), '없는구');
    await user.click(screen.getByRole('button', { name: '지역 가격 조회' }));
    expect(await screen.findByRole('status')).toHaveTextContent(reason);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/네이버 장소 결과가 필요하면/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: name => name.includes('주유소') && name.includes('(') })).not.toBeInTheDocument();
  });
});
