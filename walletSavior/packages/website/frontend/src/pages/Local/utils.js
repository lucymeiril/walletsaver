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

/** 네이버 원본 카테고리 기반 서브카테고리 맵 생성 */
export function buildSubcategories(items) {
  const map = {};
  items.forEach(item => {
    const cat = item.category || '';
    if (cat) {
      if (!map[cat]) map[cat] = [];
      if (!map[cat].includes(item)) map[cat].push(item);
    }
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
