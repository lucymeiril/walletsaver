/**
 * LocalPage 전용 데이터 — 주유소, 식당, 레시피 정보.
 * LocalPage.jsx에서만 사용됨. 다른 페이지는 API에서 실시간 조회.
 *
 * 주유소/식당 데이터는 Naver 실시간 검색으로 보완되지만
 * 기본 표시용으로 이 데이터를 유지합니다.
 */

// ===== 유틸 =====
export function fmt(n) {
  if (n == null) return '';
  return n.toLocaleString('ko-KR');
}

// ===== 주유소 (LocalPage 기본 표시용) =====
export const GAS_STATIONS = [
  { name:"현대 셀프 강남점",      addr:"강남구 역삼동 123", gasoline:1598, diesel:1438, lpg:989,  brand:"현대" },
  { name:"SK 에너지 서초점",      addr:"서초구 서초동 456", gasoline:1612, diesel:1452, lpg:995,  brand:"SK" },
  { name:"GS 셀프 잠실점",        addr:"송파구 잠실동 789", gasoline:1605, diesel:1445, lpg:992,  brand:"GS" },
  { name:"S-OIL 방배점",          addr:"서초구 방배동 234", gasoline:1625, diesel:1468, lpg:1002, brand:"S-OIL" },
  { name:"알뜰 셀프 대치점",      addr:"강남구 대치동 567", gasoline:1578, diesel:1418, lpg:975,  brand:"알뜰" },
  { name:"현대 오일뱅크 삼성점",    addr:"강남구 삼성동 890", gasoline:1632, diesel:1472, lpg:null, brand:"현대" },
  { name:"SK 셀프 논현점",         addr:"강남구 논현동 345", gasoline:1589, diesel:1429, lpg:985,  brand:"SK" },
  { name:"알뜰 주유소 개포점",     addr:"강남구 개포동 211", gasoline:1570, diesel:1410, lpg:970,  brand:"알뜰" },
];

// ===== 식당 (LocalPage 기본 표시용) =====
export const RESTAURANTS = [
  { name:"홍콩반점 역삼역점",  addr:"강남구 역삼동 123-1", cat:"중식", menu:"짜장면",        price:5500,  rating:4.2 },
  { name:"전설의 짬뽕 강남점", addr:"강남구 역삼동 145-2", cat:"중식", menu:"짜장면",        price:6000,  rating:4.0 },
  { name:"메가커피 테헤란점",  addr:"강남구 역삼동 201-1", cat:"카페", menu:"아메리카노",    price:1500,  rating:4.5 },
  { name:"스타벅스 강남역점",  addr:"강남구 역삼동 222",   cat:"카페", menu:"아메리카노",    price:4500,  rating:4.8 },
  { name:"백채김치찌개 역삼점",addr:"강남구 역삼동 301",   cat:"한식", menu:"김치찌개",      price:7500,  rating:4.4 },
  { name:"고기굼터 강남점",    addr:"강남구 역삼동 333-2", cat:"한식", menu:"삼겹살(1인분)", price:13000, rating:4.6 },
  { name:"명동칼국수 서초점",  addr:"서초구 서초동 111",   cat:"한식", menu:"칼국수",        price:8000,  rating:4.1 },
];
export const LOCAL_AVGS = { "짜장면":6500, "아메리카노":3000, "김치찌개":8000, "칼국수":7500, "삼겹살(1인분)":15000 };

// ===== 레시피 (집밥 vs 외식 비교 — LocalPage용) =====
export const RECIPES = [
  {
    name:"짜장면", servings:2, eatingOut:6500, category:"중식", icon:"🍜",
    ingredients: [
      { name:"중화면", amount:"2인분", cost:1200 },
      { name:"춘장", amount:"60g", cost:480 },
      { name:"양파", amount:"1개", cost:500 },
      { name:"돼지고기", amount:"100g", cost:1200 },
      { name:"호박", amount:"1/3개", cost:240 },
      { name:"식용유", amount:"15ml", cost:45 },
    ]
  },
  {
    name:"김치찌개", servings:2, eatingOut:8000, category:"한식", icon:"🍲",
    ingredients: [
      { name:"김치", amount:"200g", cost:2200 },
      { name:"돼지고기", amount:"150g", cost:1800 },
      { name:"두부", amount:"반모", cost:900 },
      { name:"대파", amount:"조금", cost:840 },
      { name:"고추장", amount:"10g", cost:70 },
    ]
  },
  {
    name:"된장찌개", servings:2, eatingOut:7500, category:"한식", icon:"🥘",
    ingredients: [
      { name:"된장", amount:"30g", cost:300 },
      { name:"두부", amount:"반모", cost:900 },
      { name:"감자", amount:"반개", cost:250 },
      { name:"양파", amount:"반개", cost:250 },
      { name:"호박", amount:"1/3개", cost:240 },
      { name:"대파", amount:"조금", cost:560 },
    ]
  },
  {
    name:"계란볶음밥", servings:1, eatingOut:7000, category:"한식", icon:"🍳",
    ingredients: [
      { name:"밥", amount:"1공기", cost:500 },
      { name:"계란", amount:"2개", cost:400 },
      { name:"대파", amount:"조금", cost:280 },
      { name:"식용유", amount:"10ml", cost:30 },
    ]
  },
  {
    name:"삼겹살 구이", servings:1, eatingOut:15000, category:"한식", icon:"🥩",
    ingredients: [
      { name:"삼겹살", amount:"200g", cost:3800 },
      { name:"쌈채소", amount:"100g", cost:1200 },
      { name:"마늘", amount:"20g", cost:300 },
      { name:"쌈장", amount:"20g", cost:160 },
    ]
  },
];

// 레시피 비용 계산
export function calcRecipeCost(recipe) {
  const total = recipe.ingredients.reduce((s, i) => s + i.cost, 0);
  const savings = recipe.eatingOut - total;
  const pct = Math.round((savings / recipe.eatingOut) * 100);
  return { total, savings, pct };
}
