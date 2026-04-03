/* 카테고리 트리 */
export const categories = [
  {
    id: 'cat-1', name: '농축산물', children: [
      {
        id: 'cat-1-1', name: '육류', children: [
          { id: 'cat-1-1-1', name: '소고기', productCount: 5, attributes: { grade: '1++등급', origin: '국내산', storage: '냉장' } },
          { id: 'cat-1-1-2', name: '돼지고기', productCount: 4, attributes: { grade: '등급없음', origin: '국내산', storage: '냉장' } },
          { id: 'cat-1-1-3', name: '닭고기', productCount: 3, attributes: { grade: '등급없음', origin: '국내산', storage: '냉장' } },
        ],
      },
      {
        id: 'cat-1-2', name: '채소', children: [
          { id: 'cat-1-2-1', name: '엽경채류', productCount: 3, attributes: { origin: '국내산', storage: '냉장' } },
          { id: 'cat-1-2-2', name: '과채류', productCount: 2, attributes: { origin: '국내산', storage: '상온' } },
        ],
      },
      {
        id: 'cat-1-3', name: '과일', children: [
          { id: 'cat-1-3-1', name: '국산 과일', productCount: 3, attributes: { origin: '국내산', storage: '상온' } },
          { id: 'cat-1-3-2', name: '수입 과일', productCount: 2, attributes: { origin: '수입산', storage: '냉장' } },
        ],
      },
    ],
  },
  {
    id: 'cat-2', name: '수산물', children: [
      { id: 'cat-2-1', name: '생선', productCount: 2, attributes: { origin: '국내산', storage: '냉동' } },
      { id: 'cat-2-2', name: '갑각류', productCount: 1, attributes: { origin: '국내산', storage: '냉동' } },
    ],
  },
  {
    id: 'cat-3', name: '가공식품', children: [
      { id: 'cat-3-1', name: '유제품', productCount: 2, attributes: { origin: '국내산', storage: '냉장' } },
      { id: 'cat-3-2', name: '면류', productCount: 1, attributes: { origin: '국내산', storage: '상온' } },
    ],
  },
];

/* 상품 */
export const products = [
  { id: 'p-1',  name: '한우 등심 1등급',   category: '소고기',   unit: '100g', basePrice: 8900,  currentAvg: 9200,  tier: 'good' },
  { id: 'p-2',  name: '한우 갈비 1등급',   category: '소고기',   unit: '100g', basePrice: 12500, currentAvg: 11800, tier: 'great' },
  { id: 'p-3',  name: '호주산 척아이롤',   category: '소고기',   unit: '100g', basePrice: 3200,  currentAvg: 2900,  tier: 'ultra' },
  { id: 'p-4',  name: '미국산 부채살',     category: '소고기',   unit: '100g', basePrice: 3800,  currentAvg: 3600,  tier: 'great' },
  { id: 'p-5',  name: '한우 안심 1++등급', category: '소고기',   unit: '100g', basePrice: 15000, currentAvg: 14200, tier: 'great' },
  { id: 'p-6',  name: '삼겹살 국내산',     category: '돼지고기', unit: '100g', basePrice: 2200,  currentAvg: 2350,  tier: 'good' },
  { id: 'p-7',  name: '목살 국내산',       category: '돼지고기', unit: '100g', basePrice: 2000,  currentAvg: 1850,  tier: 'great' },
  { id: 'p-8',  name: '등갈비 국내산',     category: '돼지고기', unit: '100g', basePrice: 1800,  currentAvg: 1900,  tier: 'good' },
  { id: 'p-9',  name: '수입 삼겹살',       category: '돼지고기', unit: '100g', basePrice: 1400,  currentAvg: 1100,  tier: 'ultra' },
  { id: 'p-10', name: '닭가슴살',          category: '닭고기',   unit: '100g', basePrice: 1200,  currentAvg: 1150,  tier: 'great' },
  { id: 'p-11', name: '닭다리',            category: '닭고기',   unit: '100g', basePrice: 900,   currentAvg: 950,   tier: 'good' },
  { id: 'p-12', name: '통닭 (마리)',       category: '닭고기',   unit: '1마리', basePrice: 7500,  currentAvg: 7200,  tier: 'great' },
  { id: 'p-13', name: '배추',              category: '엽경채류', unit: '1포기', basePrice: 3500,  currentAvg: 4200,  tier: 'wait' },
  { id: 'p-14', name: '시금치',            category: '엽경채류', unit: '1단',  basePrice: 2800,  currentAvg: 2600,  tier: 'great' },
  { id: 'p-15', name: '양배추',            category: '엽경채류', unit: '1통',  basePrice: 3200,  currentAvg: 3400,  tier: 'good' },
  { id: 'p-16', name: '토마토',            category: '과채류',   unit: '1kg',  basePrice: 5500,  currentAvg: 5800,  tier: 'good' },
  { id: 'p-17', name: '오이',              category: '과채류',   unit: '10개', basePrice: 8000,  currentAvg: 7200,  tier: 'great' },
  { id: 'p-18', name: '사과 (부사)',       category: '국산 과일', unit: '10개', basePrice: 25000, currentAvg: 28000, tier: 'wait' },
  { id: 'p-19', name: '바나나',            category: '수입 과일', unit: '1송이', basePrice: 4500,  currentAvg: 3800,  tier: 'ultra' },
  { id: 'p-20', name: '고등어',            category: '생선',     unit: '1마리', basePrice: 3500,  currentAvg: 3200,  tier: 'great' },
];

/* 가격 이력 생성 (상품별 90일) */
function generatePriceHistory(product, days = 90) {
  const history = [];
  const now = Date.now();
  const dayMs = 86400000;
  let price = product.basePrice;
  for (let i = days; i >= 0; i--) {
    const change = (Math.random() - 0.48) * product.basePrice * 0.03;
    price = Math.max(price * 0.7, Math.min(price * 1.3, price + change));
    history.push({
      date: new Date(now - i * dayMs).toISOString().slice(0, 10),
      price: Math.round(price),
      source: ['KAMIS', 'OPINET', '이마트', '쿠팡'][Math.floor(Math.random() * 4)],
    });
  }
  return history;
}

export const priceHistories = Object.fromEntries(
  products.map(p => [p.id, generatePriceHistory(p)])
);

/* 가격 이상치 */
export const priceOutliers = [
  { id: 'o-1', productId: 'p-1',  productName: '한우 등심 1등급', date: '2025-07-10', price: 15800, avgPrice: 9200, deviation: 71.7, source: '쿠팡' },
  { id: 'o-2', productId: 'p-6',  productName: '삼겹살 국내산',   date: '2025-07-09', price: 980,   avgPrice: 2350, deviation: -58.3, source: 'KAMIS' },
  { id: 'o-3', productId: 'p-13', productName: '배추',            date: '2025-07-08', price: 8500,  avgPrice: 4200, deviation: 102.4, source: '이마트' },
  { id: 'o-4', productId: 'p-18', productName: '사과 (부사)',     date: '2025-07-07', price: 45000, avgPrice: 28000, deviation: 60.7, source: 'KAMIS' },
  { id: 'o-5', productId: 'p-19', productName: '바나나',          date: '2025-07-06', price: 1200,  avgPrice: 3800, deviation: -68.4, source: '쿠팡' },
];

/* 키워드 */
export const keywords = [
  { id: 'kw-1',  keyword: '삼겹살',     searchCount: 4520, synonyms: ['돼지고기', '구이용'], categoryId: 'cat-1-1-2' },
  { id: 'kw-2',  keyword: '한우',       searchCount: 3890, synonyms: ['소고기', '국내산소'], categoryId: 'cat-1-1-1' },
  { id: 'kw-3',  keyword: '계란',       searchCount: 3200, synonyms: ['달걀', '유정란'], categoryId: 'cat-3-1' },
  { id: 'kw-4',  keyword: '사과',       searchCount: 2980, synonyms: ['부사', '아오리'], categoryId: 'cat-1-3-1' },
  { id: 'kw-5',  keyword: '배추',       searchCount: 2750, synonyms: ['절임배추', '김장배추'], categoryId: 'cat-1-2-1' },
  { id: 'kw-6',  keyword: '바나나',     searchCount: 2640, synonyms: ['수입과일'], categoryId: 'cat-1-3-2' },
  { id: 'kw-7',  keyword: '닭가슴살',   searchCount: 2510, synonyms: ['닭고기', '다이어트'], categoryId: 'cat-1-1-3' },
  { id: 'kw-8',  keyword: '양파',       searchCount: 2380, synonyms: ['양파채'], categoryId: 'cat-1-2-2' },
  { id: 'kw-9',  keyword: '토마토',     searchCount: 2120, synonyms: ['방울토마토', '스테비아토마토'], categoryId: 'cat-1-2-2' },
  { id: 'kw-10', keyword: '우유',       searchCount: 1950, synonyms: ['흰우유', '저지방우유'], categoryId: 'cat-3-1' },
  { id: 'kw-11', keyword: '오이',       searchCount: 1820, synonyms: ['백오이', '취청오이'], categoryId: 'cat-1-2-2' },
  { id: 'kw-12', keyword: '고등어',     searchCount: 1750, synonyms: ['생선', '고등어구이'], categoryId: 'cat-2-1' },
  { id: 'kw-13', keyword: '시금치',     searchCount: 1680, synonyms: ['나물'], categoryId: 'cat-1-2-1' },
  { id: 'kw-14', keyword: '목살',       searchCount: 1540, synonyms: ['돼지목살', '구이용'], categoryId: 'cat-1-1-2' },
  { id: 'kw-15', keyword: '감자',       searchCount: 1420, synonyms: ['알감자'], categoryId: 'cat-1-2-2' },
  { id: 'kw-16', keyword: '양배추',     searchCount: 1350, synonyms: ['캐비지'], categoryId: 'cat-1-2-1' },
  { id: 'kw-17', keyword: '돼지갈비',   searchCount: 1280, synonyms: ['등갈비', '갈비'], categoryId: 'cat-1-1-2' },
  { id: 'kw-18', keyword: '마늘',       searchCount: 1190, synonyms: ['깐마늘', '다진마늘'], categoryId: 'cat-1-2-2' },
  { id: 'kw-19', keyword: '당근',       searchCount: 1050, synonyms: ['미니당근'], categoryId: 'cat-1-2-2' },
  { id: 'kw-20', keyword: '파',         searchCount: 980,  synonyms: ['대파', '쪽파'], categoryId: 'cat-1-2-1' },
  { id: 'kw-21', keyword: '콩나물',     searchCount: 920,  synonyms: ['숙주나물'], categoryId: 'cat-1-2-1' },
  { id: 'kw-22', keyword: '두부',       searchCount: 860,  synonyms: ['연두부', '순두부'], categoryId: 'cat-3-2' },
  { id: 'kw-23', keyword: '라면',       searchCount: 810,  synonyms: ['컵라면', '봉지라면'], categoryId: 'cat-3-2' },
  { id: 'kw-24', keyword: '새우',       searchCount: 780,  synonyms: ['대하', '꽃새우'], categoryId: 'cat-2-2' },
  { id: 'kw-25', keyword: '갈치',       searchCount: 720,  synonyms: ['은갈치', '먹갈치'], categoryId: 'cat-2-1' },
  { id: 'kw-26', keyword: '딸기',       searchCount: 680,  synonyms: ['설향', '킹스베리'], categoryId: 'cat-1-3-1' },
  { id: 'kw-27', keyword: '수박',       searchCount: 620,  synonyms: ['애플수박'], categoryId: 'cat-1-3-1' },
  { id: 'kw-28', keyword: '복숭아',     searchCount: 560,  synonyms: ['백도', '황도'], categoryId: 'cat-1-3-1' },
  { id: 'kw-29', keyword: '참치',       searchCount: 510,  synonyms: ['참치캔', '생참치'], categoryId: 'cat-2-1' },
  { id: 'kw-30', keyword: '김치',       searchCount: 480,  synonyms: ['포기김치', '깍두기'], categoryId: 'cat-3-1' },
];

/* 대시보드 통계 */
export const dashboardStats = {
  totalProducts: products.length,
  totalPriceRecords: products.length * 91,
  totalCategories: 15,
  totalKeywords: keywords.length,
  lastUpdated: '2025-07-13T14:32:00',
  qualityScore: 87,
  recentIngestions: [
    { id: 'ri-1', source: 'KAMIS',  count: 1240, date: '2025-07-13', status: 'success' },
    { id: 'ri-2', source: '이마트', count: 890,  date: '2025-07-13', status: 'success' },
    { id: 'ri-3', source: '쿠팡',  count: 650,  date: '2025-07-12', status: 'warning' },
    { id: 'ri-4', source: 'OPINET', count: 320,  date: '2025-07-12', status: 'success' },
    { id: 'ri-5', source: 'KOSIS',  count: 180,  date: '2025-07-11', status: 'error' },
  ],
};

/* 분석 — 카테고리별 평균가격 */
export const categoryAvgPrices = [
  { category: '소고기',   avgPrice: 8340 },
  { category: '돼지고기', avgPrice: 1825 },
  { category: '닭고기',   avgPrice: 3100 },
  { category: '엽경채류', avgPrice: 3400 },
  { category: '과채류',   avgPrice: 6500 },
  { category: '과일',     avgPrice: 18600 },
  { category: '생선',     avgPrice: 3200 },
  { category: '유제품',   avgPrice: 2800 },
];

/* 분석 — 데이터 품질 리포트 */
export const qualityReport = {
  outliers: priceOutliers.length,
  duplicates: 23,
  missingFields: 8,
  totalRecords: products.length * 91,
  completeness: 94.2,
  accuracy: 87.5,
};

/* 분석 — 크롤 데이터 출처별 통계 */
export const sourceStats = [
  { source: 'KAMIS',  records: 12400, lastCrawl: '2025-07-13T14:00:00', status: 'active' },
  { source: 'OPINET', records: 8900,  lastCrawl: '2025-07-13T12:00:00', status: 'active' },
  { source: '이마트', records: 6500,  lastCrawl: '2025-07-13T10:00:00', status: 'active' },
  { source: '쿠팡',  records: 4200,  lastCrawl: '2025-07-12T22:00:00', status: 'warning' },
  { source: 'KOSIS',  records: 1800,  lastCrawl: '2025-07-11T08:00:00', status: 'error' },
];

/* 가격 티어 기준 */
export const priceTiers = {
  ultra: { label: '초특가', threshold: 70, color: 'var(--tier-ultra)' },
  great: { label: '특가',   threshold: 85, color: 'var(--tier-great)' },
  good:  { label: '적정',   threshold: 105, color: 'var(--tier-good)' },
  wait:  { label: '관망',   threshold: 120, color: 'var(--tier-wait)' },
  bad:   { label: '비쌈',   threshold: Infinity, color: 'var(--tier-bad)' },
};
