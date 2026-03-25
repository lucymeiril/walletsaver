/**
 * 지갑 지키미 — 더미 데이터.
 * 실제 서비스에서는 API 호출로 교체.
 * 이 파일만 교체하면 전체 데이터가 바뀜 (결합도 제로).
 */

const PRODUCTS = [
  { id:1,  name:"양파",   icon:"🧅", cat:"채소류 > 근채류",  unit:"1kg",   avg:2350, cur:2380, low:1980, high:3200, stores:{ emart:2280, homeplus:2380, lotte:2490, costco:2190 } },
  { id:2,  name:"삼겹살", icon:"🥩", cat:"축산물 > 돼지고기", unit:"100g",  avg:1850, cur:1680, low:1100, high:2400, stores:{ emart:1680, homeplus:1790, lotte:1650, costco:1520 } },
  { id:3,  name:"계란",   icon:"🥚", cat:"축산물 > 란류",    unit:"30구",  avg:6200, cur:5980, low:4980, high:8900, stores:{ emart:5980, homeplus:6290, lotte:6100, costco:5490 } },
  { id:4,  name:"사과",   icon:"🍎", cat:"과일류 > 사과",    unit:"1kg",   avg:4800, cur:5200, low:3200, high:7800, stores:{ emart:5100, homeplus:5300, lotte:5200, costco:4800 } },
  { id:5,  name:"우유",   icon:"🥛", cat:"유제품 > 우유",    unit:"1L",    avg:2650, cur:2590, low:2200, high:3100, stores:{ emart:2590, homeplus:2680, lotte:2620, costco:2390 } },
  { id:6,  name:"쌀",     icon:"🍚", cat:"곡류 > 쌀",       unit:"10kg",  avg:28500,cur:27900,low:24000,high:35000,stores:{ emart:27900,homeplus:28200,lotte:28500,costco:26500} },
  { id:7,  name:"배추",   icon:"🥬", cat:"채소류 > 엽경채류", unit:"1포기", avg:3200, cur:2800, low:1800, high:5500, stores:{ emart:2800, homeplus:2950, lotte:2900, costco:2600 } },
  { id:8,  name:"감자",   icon:"🥔", cat:"채소류 > 근채류",  unit:"1kg",   avg:2800, cur:3100, low:2100, high:4200, stores:{ emart:3100, homeplus:2900, lotte:3050, costco:2700 } },
  { id:9,  name:"닭가슴살",icon:"🍗",cat:"축산물 > 닭고기",  unit:"1kg",   avg:8500, cur:7900, low:6500, high:11000,stores:{ emart:7900, homeplus:8200, lotte:8000, costco:7200 } },
  { id:10, name:"두부",   icon:"🧊", cat:"가공식품 > 두부",  unit:"1모",   avg:1800, cur:1650, low:1200, high:2400, stores:{ emart:1650, homeplus:1700, lotte:1650, costco:1500 } },
  { id:11, name:"식용유", icon:"🫒", cat:"조미료 > 유지류",  unit:"1.8L",  avg:5800, cur:5500, low:4200, high:7500, stores:{ emart:5500, homeplus:5700, lotte:5600, costco:4900 } },
  { id:12, name:"라면",   icon:"🍜", cat:"가공식품 > 면류",  unit:"5입",   avg:3900, cur:3500, low:2900, high:4500, stores:{ emart:3500, homeplus:3600, lotte:3450, costco:3200 } },
];

// 30일 가격 히스토리 생성기
function genPriceHistory(product, days = 30) {
  const data = [];
  const base = product.avg;
  for (let i = days; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    const noise = (Math.random() - 0.5) * (product.high - product.low) * 0.4;
    const seasonal = Math.sin(i / 7 * Math.PI) * (product.high - product.low) * 0.1;
    let price = Math.round(base + noise + seasonal);
    price = Math.max(product.low, Math.min(product.high, price));
    data.push({ date: d, price });
  }
  return data;
}

const HOTDEALS = [
  { id:1, title:"이마트 삼겹살 100g 1,100원 시작! 정기 할인 돌아왔어요", source:"뽐뿌", price:1100, origPrice:1850, time:"3분 전", cat:"food", views:342, comments:28 },
  { id:2, title:"코스트코 양배추 1kg 5,190원 (정가 6,590원)", source:"어미새", price:5190, origPrice:6590, time:"12분 전", cat:"food", views:156, comments:8 },
  { id:3, title:"LG 울트라기어 27인치 QHD 모니터 역대최저 297,000원", source:"루리웹", price:297000, origPrice:399000, time:"25분 전", cat:"electronics", views:892, comments:67 },
  { id:4, title:"무신사 봄 세일 최대 70% + 추가 15% 쿠폰", source:"에펨코리아", price:null, origPrice:null, time:"38분 전", cat:"fashion", views:445, comments:23 },
  { id:5, title:"홈플러스 계란 30구 4,980원 (역대급 가격)", source:"뽐뿌", price:4980, origPrice:6200, time:"1시간 전", cat:"food", views:1203, comments:89 },
  { id:6, title:"다이슨 에어랩 리퍼 39만원 (정가 69만원)", source:"어미새", price:390000, origPrice:690000, time:"1시간 전", cat:"living", views:2341, comments:156 },
  { id:7, title:"에어팟 프로 2 USB-C 199,000원 (카드할인 적용)", source:"루리웹", price:199000, origPrice:329000, time:"2시간 전", cat:"electronics", views:1890, comments:98 },
  { id:8, title:"이마트 GAP 양파 1.5kg 2,480원 주간특가", source:"뽐뿌", price:2480, origPrice:3980, time:"2시간 전", cat:"food", views:445, comments:12 },
  { id:9, title:"나이키 에어맥스 97 직구 89,000원 (관부가세 포함)", source:"에펨코리아", price:89000, origPrice:179000, time:"3시간 전", cat:"fashion", views:678, comments:34 },
  { id:10, title:"GS25 도시락 1+1 행사 (3/14~3/20)", source:"뽐뿌", price:null, origPrice:null, time:"3시간 전", cat:"food", views:234, comments:15 },
  { id:11, title:"쿠팡 롯데 우유 1L 2,190원 로켓배송", source:"어미새", price:2190, origPrice:2650, time:"4시간 전", cat:"food", views:567, comments:19 },
  { id:12, title:"샤오미 로봇청소기 X10+ 최저가 갱신 449,000원", source:"루리웹", price:449000, origPrice:699000, time:"5시간 전", cat:"electronics", views:1234, comments:78 },
  { id:13, title:"햇반 210g 24입 18,900원 스마일결제", source:"뽐뿌", price:18900, origPrice:28000, time:"6시간 전", cat:"food", views:892, comments:31 },
  { id:14, title:"탑텐 베이직 티셔츠 1+1 15,000원", source:"에펨코리아", price:15000, origPrice:30000, time:"7시간 전", cat:"fashion", views:310, comments:14 },
  { id:15, title:"오픈AI 챗GPT 플러스 1년 구독 20% 할인 프로모션코드", source:"루리웹", price:192, origPrice:240, time:"8시간 전", cat:"living", views:5129, comments:215 },
  { id:16, title:"농협 안심한우 1등급 등심 500g 39,000원", source:"어미새", price:39000, origPrice:59000, time:"10시간 전", cat:"food", views:1024, comments:47 }
];

const MART_DATA = {
  emart: {
    name: "이마트", color: "#FFD700", period: "3/14(목) ~ 3/20(수)",
    items: [
      { name:"GAP 양파 1.5kg", orig:3980, sale:2480, disc:38, event:"주간특가" },
      { name:"한우 등심 100g", orig:8900, sale:5900, disc:34, event:"축산대전" },
      { name:"삼겹살 600g", orig:14900, sale:9900, disc:34, event:"1+1" },
      { name:"국내산 계란 30구", orig:7980, sale:5980, disc:25, event:"위크딜" },
      { name:"CJ 햇반 210g x12", orig:12900, sale:8900, disc:31, event:"가공식품 SALE" },
      { name:"오뚜기 진라면 5P", orig:4200, sale:2900, disc:31, event:"라면번들" },
      { name:"매일우유 1L", orig:2990, sale:2390, disc:20, event:"유제품 할인" },
      { name:"신선 딸기 500g", orig:8900, sale:6900, disc:22, event:"제철 과일" },
    ]
  },
  homeplus: {
    name: "홈플러스", color: "#FF6B35", period: "3/13(수) ~ 3/19(화)",
    items: [
      { name:"호주산 청정우 채끝 100g", orig:5900, sale:3900, disc:34, event:"수입육 할인" },
      { name:"풀무원 두부 2입", orig:3800, sale:2500, disc:34, event:"1+1" },
      { name:"양배추 1통", orig:4500, sale:2900, disc:36, event:"야채도매" },
      { name:"CJ 비비고 만두 1kg", orig:9800, sale:6900, disc:30, event:"냉동식품" },
      { name:"남양 맛있는우유 1L", orig:2800, sale:1990, disc:29, event:"유제품 해피위크" },
      { name:"국산 고등어 2마리", orig:7900, sale:5900, disc:25, event:"수산大전" },
    ]
  },
  lotte: {
    name: "롯데마트", color: "#E4002B", period: "3/14(목) ~ 3/20(수)",
    items: [
      { name:"통삼겹 수육용 1kg", orig:19900, sale:12900, disc:35, event:"정육코너" },
      { name:"국내산 사과 5입", orig:12900, sale:8900, disc:31, event:"과일 대전" },
      { name:"오리온 초코파이 24입", orig:8900, sale:5900, disc:34, event:"과자번들" },
      { name:"서울우유 1L 2입", orig:5200, sale:3900, disc:25, event:"2입 묶음" },
      { name:"감자 3kg", orig:9900, sale:6900, disc:30, event:"알뜰장보기" },
    ]
  },
  costco: {
    name: "코스트코", color: "#E31837", period: "3/16(토) ~ 4/12(토)",
    items: [
      { name:"절단 양배추 1kg", orig:6590, sale:5190, disc:21, event:"코스트코 할인" },
      { name:"밤 1망 2kg", orig:14990, sale:10490, disc:30, event:"코스트코 할인" },
      { name:"덴마크 유기농우유 2.3L", orig:8990, sale:7290, disc:19, event:"코스트코 할인" },
      { name:"스모크 소시지 793g", orig:17890, sale:14390, disc:20, event:"코스트코 할인" },
      { name:"킹크랩 다리 1.5kg", orig:89900, sale:69900, disc:22, event:"코스트코 할인" },
      { name:"이롬 영양건강식 21포", orig:24990, sale:19990, disc:20, event:"코스트코 할인" },
    ]
  }
};

const GAS_STATIONS = [
  { name:"현대 셀프 강남점", addr:"강남구 역삼동 123", gasoline:1598, diesel:1438, lpg:989, brand:"현대" },
  { name:"SK 에너지 서초점", addr:"서초구 서초동 456", gasoline:1612, diesel:1452, lpg:995, brand:"SK" },
  { name:"GS 셀프 잠실점",  addr:"송파구 잠실동 789", gasoline:1605, diesel:1445, lpg:992, brand:"GS" },
  { name:"S-OIL 방배점",    addr:"서초구 방배동 234", gasoline:1625, diesel:1468, lpg:1002, brand:"S-OIL" },
  { name:"알뜰 셀프 대치점", addr:"강남구 대치동 567", gasoline:1578, diesel:1418, lpg:975, brand:"알뜰" },
  { name:"현대 오일뱅크 삼성점",addr:"강남구 삼성동 890",gasoline:1632, diesel:1472, lpg:null, brand:"현대" },
  { name:"SK 셀프 논현점",  addr:"강남구 논현동 345", gasoline:1589, diesel:1429, lpg:985, brand:"SK" },
  { name:"알뜰 주유소 개포점", addr:"강남구 개포동 211", gasoline:1570, diesel:1410, lpg:970, brand:"알뜰" },
  { name:"GS칼텍스 대모산점", addr:"강남구 일원동 45", gasoline:1620, diesel:1460, lpg:998, brand:"GS" },
  { name:"현대오일뱅크 도곡점", addr:"강남구 도곡동 12", gasoline:1645, diesel:1485, lpg:1010, brand:"현대" }
];

const LOCAL_AVGS = {
  "짜장면": 6500,
  "아메리카노": 3000,
  "김치찌개": 8000,
  "칼국수": 7500,
  "삼겹살(1인분)": 15000
};

const RESTAURANTS = [
  { name:"홍콩반점 역삼역점", addr:"강남구 역삼동 123-1", cat:"중식", menu:"짜장면", price:5500, rating:4.2 },
  { name:"전설의 짬뽕 강남점", addr:"강남구 역삼동 145-2", cat:"중식", menu:"짜장면", price:6000, rating:4.0 },
  { name:"메가커피 테헤란점", addr:"강남구 역삼동 201-1", cat:"카페", menu:"아메리카노", price:1500, rating:4.5 },
  { name:"컴포즈커피 역삼점", addr:"강남구 역삼동 210-4", cat:"카페", menu:"아메리카노", price:1500, rating:4.3 },
  { name:"스타벅스 강남역점", addr:"강남구 역삼동 222", cat:"카페", menu:"아메리카노", price:4500, rating:4.8 },
  { name:"백채김치찌개 역삼점", addr:"강남구 역삼동 301", cat:"한식", menu:"김치찌개", price:7500, rating:4.4 },
  { name:"고기굼터 강남점", addr:"강남구 역삼동 333-2", cat:"한식", menu:"삼겹살(1인분)", price:13000, rating:4.6 },
  { name:"명동칼국수 서초점", addr:"서초구 서초동 111", cat:"한식", menu:"칼국수", price:8000, rating:4.1 },
];

const COMMUNITY_POSTS = [
  { id:1, title:"이마트 삼겹살 100g 1,100원 시작됐어요! 앞다리 정기할인", cat:"마트", author:"절약왕", time:"5분 전", views:342, comments:28, priceVsAvg: -40 },
  { id:2, title:"쿠팡 로켓배송 계란 30구 4,790원 (역대급)", cat:"온라인", author:"핫딜러", time:"15분 전", views:1203, comments:89, priceVsAvg: -23 },
  { id:3, title:"동네 중국집 짜장면 5,000원인데 괜찮은 건가요?", cat:"외식", author:"먹보", time:"30분 전", views:89, comments:12, priceVsAvg: null },
  { id:4, title:"코스트코 킹크랩 다리 1.5kg 69,900원 구매 후기", cat:"마트", author:"코스트코러버", time:"1시간 전", views:567, comments:34, priceVsAvg: -22 },
  { id:5, title:"GS25 도시락 1+1 오늘까지! 가성비 끝판왕", cat:"기타", author:"편의점마스터", time:"2시간 전", views:234, comments:15, priceVsAvg: null },
  { id:6, title:"홈플러스 양배추 1통 2,900원 세일 중", cat:"마트", author:"장보기달인", time:"3시간 전", views:178, comments:8, priceVsAvg: -15 },
  { id:7, title:"배민 치킨 할인 쿠폰 괜찮은가요? 원래 얼마인지", cat:"외식", author:"치킨매니아", time:"4시간 전", views:445, comments:23, priceVsAvg: null },
  { id:8, title:"이마트 에브리데이 라면 5입 2,900원 발견", cat:"마트", author:"라면왕", time:"5시간 전", views:321, comments:19, priceVsAvg: -26 },
  { id:9, title:"메가커피 아메리카노 1500원 그대로네요", cat:"외식", author:"커피광", time:"6시간 전", views:510, comments:14, priceVsAvg: -50 },
  { id:10, title:"11번가 스팸 200g 10캔 15,900원", cat:"온라인", author:"통조림매니아", time:"7시간 전", views:890, comments:45, priceVsAvg: -32 },
  { id:11, title:"우리동네 식자재마트 대파 1단 1,500원", cat:"마트", author:"동네주민", time:"10시간 전", views:412, comments:11, priceVsAvg: -46 }
];

const COMMUNITY_FREETALK = [
  { id:1, title:"다들 이번 주말에 장 어디서 보시나요?", cat:"자유게시판", author:"주말주부", time:"10분 전", views:45, comments:5 },
  { id:2, title:"홈플러스 앱 너무 느리지 않나요ㅠ", cat:"자유게시판", author:"앱사용자", time:"1시간 전", views:120, comments:15 },
  { id:3, title:"요즘 사과값이 좀 내린 것 같아서 다행입니다", cat:"자유게시판", author:"사과러버", time:"2시간 전", views:340, comments:28 },
  { id:4, title:"알뜰 주유소 vs 동네 주유소 어딜 주로 가시나요?", cat:"자유게시판", author:"운전수", time:"5시간 전", views:89, comments:12 },
  { id:5, title:"식비 방어 꿀팁 공유합니다 (+냉장고 파먹기)", cat:"자유게시판", author:"짠테크", time:"하루 전", views:1502, comments:120 }
];

const WRITE_AUTOCOMPLETE_DB = [
  { id: 101, name: "돼지고기 앞다리 (냉장)", cat: "축산물 > 돼지고기 > 앞다리", storage: "냉장", avg: 1200, unit: "100g" },
  { id: 102, name: "돼지고기 앞다리 (냉동)", cat: "축산물 > 돼지고기 > 앞다리", storage: "냉동", avg: 850, unit: "100g" },
  { id: 103, name: "돼지고기 삼겹살 (냉장)", cat: "축산물 > 돼지고기 > 삼겹살", storage: "냉장", avg: 1850, unit: "100g" },
  { id: 104, name: "소고기 등심 (냉장/한우)", cat: "축산물 > 소고기 > 등심", storage: "냉장", avg: 8900, unit: "100g" },
  { id: 105, name: "닭가슴살 1kg (냉동)", cat: "축산물 > 닭고기 > 가슴살", storage: "냉동", avg: 6500, unit: "1kg" },
  { id: 106, name: "양파 중망 (국산)", cat: "채소류 > 근채류 > 양파", storage: "실온", avg: 2350, unit: "1kg" },
  { id: 107, name: "대파 1단 (국산)", cat: "채소류 > 조미채소 > 대파", storage: "실온", avg: 2800, unit: "1단" },
  { id: 108, name: "사과 1봉 (부사/국산)", cat: "과일류 > 사과", storage: "실온", avg: 4800, unit: "1kg" },
  { id: 109, name: "남양 맛있는 우유 1L", cat: "유제품 > 우유", storage: "냉장", avg: 2650, unit: "1L" },
  { id: 110, name: "CJ 햇반 210g", cat: "가공식품 > 즉석밥", storage: "실온", avg: 1100, unit: "1개" },
  { id: 111, name: "코카콜라 1.5L", cat: "음료 > 탄산", storage: "실온", avg: 2900, unit: "1병" },
  { id: 112, name: "농심 신라면 5입", cat: "가공식품 > 면류", storage: "실온", avg: 3900, unit: "1묶음" },
  { id: 113, name: "동원참치 라이트 150g", cat: "가공식품 > 통조림", storage: "실온", avg: 2500, unit: "1캔" },
  { id: 114, name: "종가집 썰은배추김치 1kg", cat: "반찬류 > 김치", storage: "냉장", avg: 10500, unit: "1kg" },
  { id: 115, name: "풀무원 국산콩 두부 1모", cat: "가공식품 > 두부", storage: "냉장", avg: 3500, unit: "1모" }
];
