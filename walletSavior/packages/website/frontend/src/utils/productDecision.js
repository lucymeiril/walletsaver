import { normalizeProduct } from './productActions';

function firstDefined(...values) {
  return values.find((v) => v !== undefined && v !== null && v !== '');
}

function toNumber(value, fallback = 0) {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'string') {
    const parsed = Number(value.replace(/[^0-9.-]/g, ''));
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function asArray(...values) {
  for (const value of values) {
    if (Array.isArray(value) && value.length > 0) return value;
    if (value && Array.isArray(value.data) && value.data.length > 0) return value.data;
    if (value && Array.isArray(value.items) && value.items.length > 0) return value.items;
    if (value && Array.isArray(value.history) && value.history.length > 0) return value.history;
    if (value && Array.isArray(value.sources) && value.sources.length > 0) return value.sources;
    if (value && Array.isArray(value.other_stores) && value.other_stores.length > 0) return value.other_stores;
    if (value && Array.isArray(value.stores) && value.stores.length > 0) return value.stores;
  }
  return [];
}

function normalizeHistoryEntry(entry) {
  const price = toNumber(firstDefined(entry.price, entry.current_price, entry.sale_price, entry.amount));
  if (!price) return null;
  return {
    date: firstDefined(entry.date, entry.observed_at, entry.created_at, entry.crawled_at, entry.updated_at, ''),
    price,
    source: firstDefined(entry.source_name, entry.store_name, entry.source, entry.store, ''),
  };
}

function normalizeOffer(entry) {
  const price = toNumber(firstDefined(entry.price, entry.current_price, entry.sale, entry.sale_price, entry.item_price));
  if (!price) return null;
  const originalPrice = toNumber(firstDefined(entry.original_price, entry.origPrice, entry.orig, entry.regular_price));
  return {
    sourceName: firstDefined(entry.source_name, entry.store_name, entry.source, entry.store, entry.martName, '출처'),
    sourceType: firstDefined(entry.source_type, entry.type, entry.channel, ''),
    title: firstDefined(entry.title, entry.source_title, entry.name, entry.item_name, ''),
    price,
    originalPrice,
    discount: toNumber(firstDefined(entry.discount_rate, entry.discount, entry.disc, entry.discountRate)),
    unitPrice: firstDefined(entry.standard_unit_price, entry.unit_price, entry.unitPrice, ''),
    unit: firstDefined(entry.standard_unit, entry.unit, entry.spec, ''),
    period: firstDefined(entry.period, entry.validity_period, entry.valid_until, ''),
    url: firstDefined(entry.source_url, entry.detail_url, entry.detailUrl, entry.url, entry.link, ''),
    trust: firstDefined(entry.trust_label, entry.confidence, entry.confidence_label, ''),
  };
}

export function getPriceHistorySummary(product = {}, apiHistory = []) {
  const history = asArray(apiHistory, product.price_history, product.priceHistory, product.history, product.priceHistorySummary?.history)
    .map(normalizeHistoryEntry)
    .filter(Boolean)
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));

  const embedded = product.price_history_summary || product.priceHistorySummary || {};
  const prices = history.map((h) => h.price);
  const min = toNumber(firstDefined(embedded.min, embedded.min_price, embedded.lowest_price), prices.length ? Math.min(...prices) : 0);
  const max = toNumber(firstDefined(embedded.max, embedded.max_price, embedded.highest_price), prices.length ? Math.max(...prices) : 0);
  const avg = toNumber(firstDefined(embedded.avg, embedded.average, embedded.average_price), prices.length ? Math.round(prices.reduce((sum, p) => sum + p, 0) / prices.length) : 0);
  const latest = toNumber(firstDefined(embedded.latest, embedded.latest_price), prices.at(-1) || 0);
  const previous = prices.length > 1 ? prices.at(-2) : 0;
  const trend = firstDefined(embedded.trend, latest && previous ? (latest < previous ? 'down' : latest > previous ? 'up' : 'stable') : 'unknown');
  const lastDiscountDate = firstDefined(
    embedded.last_discount_date,
    embedded.lastDiscountDate,
    history.filter((h) => avg && h.price < avg).at(-1)?.date,
    ''
  );

  return {
    history,
    hasData: history.length > 0 || min > 0 || avg > 0 || max > 0,
    sparse: history.length > 0 && history.length < 3,
    count: history.length || toNumber(firstDefined(embedded.count, embedded.reference_count)),
    min,
    avg,
    max,
    latest,
    trend,
    lastDiscountDate,
  };
}

export function getComparableOffers(product = {}, priceCompare = null) {
  const raw = asArray(
    product.comparable_offers,
    product.comparableOffers,
    product.offers,
    product.other_sources,
    product.otherStores,
    priceCompare?.other_stores,
    priceCompare?.stores,
    priceCompare?.sources,
    priceCompare?.items,
    priceCompare
  );
  const offers = raw.map(normalizeOffer).filter(Boolean);
  const p = normalizeProduct(product);
  if (p.price > 0 && !offers.some((o) => o.price === p.price && o.sourceName === (p.storeName || p.sourceType || '출처'))) {
    offers.unshift({
      sourceName: p.storeName || p.sourceType || '현재 상품',
      sourceType: p.sourceType,
      title: p.sourceTitle || p.name,
      price: p.price,
      originalPrice: p.originalPrice,
      discount: p.discount,
      unitPrice: p.standardUnitPrice,
      unit: p.standardUnit,
      period: p.period,
      url: p.sourceUrl,
      trust: '',
      current: true,
    });
  }
  return offers.sort((a, b) => a.price - b.price).slice(0, 6);
}

export function getTrustSignals(product = {}, priceTrust = null) {
  const trust = priceTrust || product.price_trust || product.priceTrust || product.trust || {};
  const signals = [];
  const score = toNumber(firstDefined(trust.hotdeal_score, trust.score, product.hotdeal_score));
  const references = toNumber(firstDefined(trust.reference_count, trust.references, product.reference_count));
  const totalVotes = toNumber(product.hotVotes) + toNumber(product.coldVotes);
  if (score) signals.push(`신뢰 점수 ${score}/100`);
  if (references) signals.push(`비교 출처 ${references}개`);
  if (firstDefined(trust.confidence, product.confidence)) signals.push(`신뢰도 ${firstDefined(trust.confidence, product.confidence)}`);
  if (firstDefined(product.source, product.source_name, product.store_name)) signals.push(`${firstDefined(product.source, product.source_name, product.store_name)} 출처`);
  if (totalVotes) signals.push(`커뮤니티 반응 🔥${toNumber(product.hotVotes)} / ❄️${toNumber(product.coldVotes)}`);
  if (toNumber(product.comments)) signals.push(`댓글 ${toNumber(product.comments)}개`);
  return signals;
}

export function getHotdealJudgment(product = {}, priceTrust = null, historySummary = null) {
  const p = normalizeProduct(product);
  const trust = priceTrust || product.price_trust || product.priceTrust || product.trust || {};
  const rationale = firstDefined(trust.rationale, trust.reason, product.hotdeal_rationale, product.rationale, '');
  const current = toNumber(firstDefined(trust.current_price, p.price));
  const low = toNumber(firstDefined(trust.historical_low_price, trust.lowest_price, historySummary?.min));
  const avg = toNumber(firstDefined(trust.historical_average_price, trust.average_price, historySummary?.avg));
  const score = toNumber(firstDefined(trust.hotdeal_score, trust.score, product.hotdeal_score));

  if (rationale) {
    return { label: score >= 85 ? '역대급 후보' : score >= 70 ? '좋은 딜' : '판단 참고', tone: score >= 70 ? 'good' : 'neutral', copy: rationale };
  }
  if (!current || (!low && !avg)) {
    return { label: '데이터 부족', tone: 'neutral', copy: '가격 이력이나 비교 출처가 아직 부족해 보수적으로 판단하세요.' };
  }
  if (low && current <= low) {
    return { label: '역대 최저가', tone: 'great', copy: '수집된 이력 기준 최저가 수준입니다. 필요하면 바로 구매할 만합니다.' };
  }
  if (avg && current <= avg * 0.9) {
    return { label: '평균보다 저렴', tone: 'good', copy: `평균가보다 약 ${Math.round((1 - current / avg) * 100)}% 저렴합니다.` };
  }
  if (avg && current <= avg * 1.05) {
    return { label: '평균가 근처', tone: 'neutral', copy: '평소 가격과 큰 차이가 없어 급하지 않으면 더 기다려도 됩니다.' };
  }
  return { label: '비싼 편', tone: 'bad', copy: '수집된 평균가보다 높습니다. 다른 판매처나 다음 행사를 확인하세요.' };
}

export function buildProductDecision(product = {}, { priceCompare = null, priceHistory = [], priceTrust = null } = {}) {
  const normalized = normalizeProduct(product);
  const historySummary = getPriceHistorySummary(product, priceHistory);
  const comparableOffers = getComparableOffers(product, priceCompare);
  const judgment = getHotdealJudgment(product, priceTrust, historySummary);
  const trustSignals = getTrustSignals(product, priceTrust);
  const channel = firstDefined(normalized.sourceType, product.channel, product.source, normalized.storeName, '온라인');
  return {
    normalized,
    channel,
    historySummary,
    comparableOffers,
    judgment,
    trustSignals,
    currentOffer: {
      sourceName: normalized.storeName || firstDefined(product.source_name, product.source, '온라인'),
      sourceType: channel,
      period: firstDefined(normalized.period, product.validity_period, product.valid_until, ''),
      unitPrice: firstDefined(normalized.standardUnitPrice, product.unit_price, ''),
      unit: normalized.standardUnit,
    },
  };
}
