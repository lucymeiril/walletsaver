/**
 * UI 상수 — 마트 정보, 카테고리 필터 등 UI 렌더링용 설정값.
 * 실제 데이터가 아닌 표시 전용 메타데이터.
 */

/** 마트 목록 (이름, 색상, 키) */
export const MARTS = [
  { key: 'emart',    name: '이마트',   color: '#FFD700' },
  { key: 'homeplus', name: '홈플러스', color: '#FF6B35' },
  { key: 'lotte',    name: '롯데마트', color: '#E4002B' },
  { key: 'costco',   name: '코스트코', color: '#E31837' },
];

/** 핫딜 카테고리 필터 */
export const HOTDEAL_FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'food', label: '식품' },
  { key: 'electronics', label: '가전' },
  { key: 'living', label: '생활' },
  { key: 'fashion', label: '패션 👗' },
];
