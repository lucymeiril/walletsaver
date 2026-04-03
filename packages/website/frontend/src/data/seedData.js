/**
 * 실제 크롤러 데이터 기반 시드 데이터.
 * realHotdeals.json / realMartDeals.json 에서 가져와
 * 각 페이지가 기대하는 형태로 변환한다.
 */
import rawHotdeals from './realHotdeals.json';
import rawMartDeals from './realMartDeals.json';

// ── placeholder image helper (mockData.js 와 동일) ──
const img = (w, h, text, bg = '1e293b', fg = '94a3b8') =>
  `https://placehold.co/${w}x${h}/${bg}/${fg}?text=${encodeURIComponent(text)}`;

// ── 카테고리 매핑 ──
function mapHotdealCat(category) {
  const lower = (category || '').toLowerCase();
  if (['식품', '마트', '컬리', '이마트', '홈플러스', '롯데마트'].some(k => lower.includes(k))) return 'food';
  if (['전자', '디지털', '가전', '컴퓨터', 'pc', 'android', 'ios', 'wearos', 'ps4', 'ps5', '스팀'].some(k => lower.includes(k))) return 'electronics';
  if (['생활', '주방', '욕실', '건강', '미용', '가구'].some(k => lower.includes(k))) return 'living';
  if (['패션', '의류', '무신사', '나이키', '아디다스', '옷'].some(k => lower.includes(k))) return 'fashion';
  return 'food'; // 대부분 쇼핑몰 핫딜은 식품 성격
}

// 시간 포맷 (crawled_at → "N분 전" 등)
function timeAgo(isoStr) {
  if (!isoStr) return '방금 전';
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '방금 전';
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}시간 전`;
  return `${Math.floor(hrs / 24)}일 전`;
}

// ========== HOTDEALS (핫딜 페이지 + 홈페이지) ==========
export const HOTDEALS = rawHotdeals.map((item, i) => ({
  id: i + 1,
  title: item.title,
  source: item.source_community || item._source,
  price: item.price || null,
  origPrice: item.original_price || null,
  time: timeAgo(item.crawled_at),
  cat: mapHotdealCat(item.category),
  views: 50 + Math.floor(Math.random() * 2000),
  comments: Math.floor(Math.random() * 50),
  hotVotes: 5 + Math.floor(Math.random() * 150),
  coldVotes: Math.floor(Math.random() * 15),
  url: item.url || '',
  thumb: img(320, 180, (item.title || '').slice(0, 6), '2d3a4a', '9ac0e8'),
  commentData: [],
}));

// ========== MART_DATA (마트 페이지 + 홈페이지) ==========
function buildMartData() {
  const grouped = {};
  for (const item of rawMartDeals) {
    const key = item.store === '코스트코' ? 'costco' : 'emart';
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(item);
  }

  const martMeta = {
    emart:   { name: '이마트',   color: '#FFD700', period: '행사 진행 중' },
    costco:  { name: '코스트코', color: '#E31837', period: '행사 진행 중' },
    homeplus:{ name: '홈플러스', color: '#FF6B35', period: '-' },
    lotte:   { name: '롯데마트', color: '#E4002B', period: '-' },
  };

  const result = {};
  for (const [key, meta] of Object.entries(martMeta)) {
    const raw = grouped[key] || [];
    // 유효기간 정보가 있으면 period 업데이트
    let period = meta.period;
    if (raw.length > 0) {
      const withDates = raw.filter(r => r.valid_from && r.valid_until);
      if (withDates.length > 0) {
        const from = new Date(withDates[0].valid_from);
        const until = new Date(withDates[0].valid_until);
        period = `${from.getMonth() + 1}/${from.getDate()} ~ ${until.getMonth() + 1}/${until.getDate()}`;
      }
    }

    result[key] = {
      name: meta.name,
      color: meta.color,
      period,
      flyerImg: img(600, 800, `${meta.name}+전단`, meta.color.replace('#', ''), '333'),
      items: raw.map(r => ({
        name: r.name,
        orig: r.original_price || r.sale_price,
        sale: r.sale_price,
        disc: r.discount_percent ? Math.round(r.discount_percent) : (r.original_price ? Math.round((1 - r.sale_price / r.original_price) * 100) : 0),
        event: r.event_name || r.category || '할인',
        img: r.image_url || img(120, 120, (r.name || '').slice(0, 4), '2d4a2d', '9ae89a'),
      })),
    };
  }
  return result;
}

export const MART_DATA = buildMartData();

// ========== COMMUNITY_POSTS (커뮤니티 핫딜 게시판) ==========
export const COMMUNITY_POSTS = rawHotdeals.slice(0, 20).map((item, i) => {
  const price = item.price;
  const avg = item.original_price || (price ? Math.round(price * 1.3) : null);
  const priceVsAvg = price && avg ? Math.round((price / avg - 1) * 100) : null;
  let verified = null;
  if (priceVsAvg !== null) {
    if (priceVsAvg <= -30) verified = 'great_deal';
    else if (priceVsAvg <= 20) verified = 'verified';
  }
  const cats = ['마트', '온라인', '기타'];
  const cat = (item.category || '').includes('마트') || (item.category || '').includes('이마트') ? '마트'
    : cats[i % cats.length];

  return {
    id: i + 1,
    title: item.title,
    cat,
    author: item.source_community || item._source,
    time: timeAgo(item.crawled_at),
    views: 50 + Math.floor(Math.random() * 1500),
    comments: Math.floor(Math.random() * 40),
    hotVotes: 5 + Math.floor(Math.random() * 120),
    coldVotes: Math.floor(Math.random() * 12),
    priceVsAvg,
    verified,
    body: item.title + (price ? `\n가격: ${price.toLocaleString('ko-KR')}원` : '') + `\n출처: ${item.source_community || item._source}`,
    images: [],
    commentData: [],
  };
});

// ========== PRODUCTS (물가비교 - 마트 딜에서 파생) ==========
function buildProducts() {
  const icons = {
    '과일': '🍎', '채소': '🥬', '육류': '🥩', '수산': '🐟', '유제품': '🥛',
    '음료': '🥤', '간식': '🍪', '커피': '☕', '가공': '🥫', '생활': '🧴',
    '건강': '💊', '냉장': '🧊', '냉동': '🧊', '주방': '🍳',
  };
  function getIcon(cat) {
    return Object.entries(icons).find(([k]) => (cat || '').includes(k))?.[1] || '🛒';
  }

  const seen = new Map();
  for (const item of rawMartDeals) {
    const name = item.name;
    if (seen.has(name)) continue;
    seen.set(name, item);
  }

  return [...seen.values()].slice(0, 20).map((d, i) => {
    const cur = d.sale_price;
    const orig = d.original_price || cur;
    const avg = Math.round((cur + orig) / 2);
    const low = Math.round(cur * 0.85);
    const high = Math.round(orig * 1.15);
    return {
      id: i + 1,
      name: d.name,
      icon: getIcon(d.category),
      cat: d.category || '기타',
      unit: d.unit || '',
      avg, cur, low, high,
      img: d.image_url || img(200, 200, (d.name || '').slice(0, 4), '2d4a2d', '9ae89a'),
      stores: {
        emart: d.store === '이마트' ? cur : Math.round(cur * (1 + Math.random() * 0.1)),
        homeplus: Math.round(cur * (1 + Math.random() * 0.08)),
        lotte: Math.round(cur * (1 + Math.random() * 0.12)),
        costco: d.store === '코스트코' ? cur : Math.round(cur * (0.9 + Math.random() * 0.1)),
      },
      stats: {
        dataDays: 180,
        records: 500 + Math.floor(Math.random() * 1000),
        confidence: [low, high],
        outliers: Math.floor(Math.random() * 20),
        avgDiscount: d.discount_percent || 15,
        discFreq: 1 + Math.random() * 2,
      },
    };
  });
}

export const products = buildProducts();

// ========== 핫딜 소스 목록 (실제 데이터 기반) ==========
export const HOTDEAL_SOURCES = [
  '전체',
  ...new Set(rawHotdeals.map(d => d.source_community).filter(Boolean)),
];

// ========== 트렌딩 검색어 (실제 핫딜 제목에서 추출) ==========
export const TRENDING = (() => {
  const freq = {};
  const keywords = ['삼겹살', '계란', '양파', '우유', '라면', '사과', '치킨', '커피',
    '모니터', '에어팟', '아이폰', '갤럭시', '노트북', 'TV', '세탁기', '냉장고',
    '기저귀', '생수', '맥주', '과자', '두부', '김치', '고구마', '감자', '딸기'];
  for (const d of rawHotdeals) {
    for (const kw of keywords) {
      if ((d.title || '').includes(kw)) freq[kw] = (freq[kw] || 0) + 1;
    }
  }
  const sorted = Object.entries(freq).sort((a, b) => b[1] - a[1]).map(e => e[0]);
  return sorted.length >= 6 ? sorted.slice(0, 8) : ['삼겹살', '계란', '양파', '코스트코', '우유', '라면', '휘발유', '사과'];
})();
