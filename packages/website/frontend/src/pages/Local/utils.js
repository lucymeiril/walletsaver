/**
 * LocalPage 유틸리티 함수 모음
 */

/** 메뉴 정보에서 대표 가격 추출 (평균/최소/최대) */
export function getRepresentativePrice(menuInfo) {
  if (!menuInfo) return null;
  let prices = [];
  if (Array.isArray(menuInfo)) {
    prices = menuInfo
      .map(m => {
        if (typeof m.price === 'number') return m.price;
        const str = String(m.price || '').replace(/[,원\s]/g, '');
        return parseInt(str, 10);
      })
      .filter(p => !isNaN(p) && p > 0);
  } else if (typeof menuInfo === 'string' && menuInfo.trim()) {
    const matches = menuInfo.match(/[\d,]+/g);
    if (matches) {
      prices = matches.map(m => parseInt(m.replace(/,/g, ''), 10)).filter(p => !isNaN(p) && p >= 1000);
    }
  }
  if (prices.length === 0) return null;
  const avg = Math.round(prices.reduce((a, b) => a + b, 0) / prices.length);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  return { avg, min, max, count: prices.length };
}

/** 메뉴 정보를 [{name, price}] 배열로 파싱. 실패 시 원본 텍스트도 반환 */
export function parseMenuItems(menuInfo) {
  if (!menuInfo) return { items: [], rawText: '' };
  if (Array.isArray(menuInfo)) {
    const items = menuInfo
      .map(m => ({
        name: m.name || m.menu || '메뉴',
        price: typeof m.price === 'number' ? m.price
          : parseInt(String(m.price || '').replace(/[,원\s]/g, ''), 10) || 0,
      }))
      .filter(m => m.price > 0);
    return { items, rawText: '' };
  }
  if (typeof menuInfo === 'string' && menuInfo.trim()) {
    const lines = menuInfo.split(/\n/).filter(l => l.trim());
    const items = [];
    const unparsed = [];
    for (const line of lines) {
      const match = line.trim().match(/^(.+?)\s+([\d,]+)\s*원?$/);
      if (match) {
        items.push({ name: match[1].trim(), price: parseInt(match[2].replace(/,/g, ''), 10) });
      } else if (line.trim()) {
        unparsed.push(line.trim());
      }
    }
    return { items, rawText: unparsed.length > 0 ? unparsed.join('\n') : '' };
  }
  return { items: [], rawText: '' };
}

/** 카테고리 병합 매핑: 네이버 세부 카테고리 → 대표 카테고리로 통합 */
const CATEGORY_MERGE_MAP = {
  '카페': ['카페', '디저트', '베이커리', '케이크', '테이크아웃', '커피', '브런치카페', '브런치'],
  '한식': ['한식', '족발', '보쌈', '생선회', '아귀찜', '해물찜', '육류', '고기요리', '국밥', '찌개', '한정식', '불고기', '비빔밥', '해장국', '냉면', '칼국수', '삼계탕', '백반', '정식'],
  '일식': ['일식', '초밥', '롤', '샤브샤브', '일식당', '라멘', '돈카츠', '돈까스', '스시', '우동', '소바', '이자카야'],
  '중식': ['중식', '중식당', '중국집', '짜장', '짬뽕'],
  '양식': ['양식', '이탈리아', '파스타', '피자', '햄버거', '스테이크', '버거', '브런치레스토랑', '패밀리레스토랑'],
  '분식': ['분식', '떡볶이', '김밥', '만두', '국수', '면'],
  '치킨': ['치킨', '닭강정', '통닭'],
  '고기': ['고기', '삼겹살', '갈비', '소고기', '돼지고기', '양고기', '곱창', '막창', '대패삼겹살', '숯불구이', '정육'],
  '패스트푸드': ['패스트푸드', '맥도날드', '롯데리아', '버거킹'],
  '뷔페': ['뷔페', 'buffet'],
  '해산물': ['해산물', '횟집', '조개', '수산물', '생선', '회'],
  '주유소': ['주유소', '주유', 'LPG', '충전소'],
  '병원': ['병원', '의원', '치과', '한의원', '약국', '내과', '외과', '안과', '피부과', '클리닉', '정형외과', '이비인후과', '산부인과'],
  '미용': ['미용', '헤어', '네일', '피부', '뷰티', '미용실'],
  '편의시설': ['편의점', '마트', '슈퍼', '대형마트', 'GS25', 'CU', '세븐일레븐'],
};

/** 네이버 카테고리 문자열을 대표 카테고리로 병합하여 서브카테고리 맵 생성 */
export function buildSubcategories(items) {
  const map = {};

  items.forEach(item => {
    const rawCat = item.category || '';
    if (!rawCat) return;

    const tokens = rawCat.split(',').map(t => t.trim());

    let mergedCategory = null;
    for (const [groupName, keywords] of Object.entries(CATEGORY_MERGE_MAP)) {
      if (tokens.some(token => keywords.some(kw => token.includes(kw)))) {
        mergedCategory = groupName;
        break;
      }
    }

    if (!mergedCategory) {
      mergedCategory = tokens[0] || '기타';
    }

    if (!map[mergedCategory]) map[mergedCategory] = [];
    map[mergedCategory].push(item);
  });

  if (Object.keys(map).length > 1) {
    map['전체'] = items;
  }
  return map;
}

/** 아이템 정렬 */
export function sortItems(items, sortBy, sortDir) {
  const sorted = [...items];
  sorted.sort((a, b) => {
    let va, vb;
    switch (sortBy) {
      case 'gasoline':
        va = a.petrol_info?.gasoline ?? Infinity;
        vb = b.petrol_info?.gasoline ?? Infinity;
        break;
      case 'diesel':
        va = a.petrol_info?.diesel ?? Infinity;
        vb = b.petrol_info?.diesel ?? Infinity;
        break;
      case 'price': {
        const pa = getRepresentativePrice(a.menu_info);
        const pb = getRepresentativePrice(b.menu_info);
        va = pa?.avg ?? (a.petrol_info?.gasoline ?? Infinity);
        vb = pb?.avg ?? (b.petrol_info?.gasoline ?? Infinity);
        break;
      }
      case 'rating':
        va = -(a.rating || 0);
        vb = -(b.rating || 0);
        break;
      case 'distance': {
        const da = typeof a.distance === 'string'
          ? parseFloat(a.distance.replace(/[^\d.]/g, '')) || Infinity
          : (a.distance ?? Infinity);
        const db = typeof b.distance === 'string'
          ? parseFloat(b.distance.replace(/[^\d.]/g, '')) || Infinity
          : (b.distance ?? Infinity);
        va = da; vb = db;
        break;
      }
      default:
        va = 0; vb = 0;
    }
    return sortDir === 'asc' ? va - vb : vb - va;
  });
  return sorted;
}

/** 주유소 카테고리 여부 판별 */
export function isGasCategory(items) {
  if (!items || items.length === 0) return false;
  return items.filter(i => i.petrol_info).length > items.length * 0.3;
}
