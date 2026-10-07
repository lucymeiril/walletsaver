import { getProductSelection, normalizeProduct } from './productActions';

const COUNT_UNITS = new Set(['개입','봉지','인분','세트','마리','회분','구','입','개','팩','봉','병','캔','손','매','롤','포','장','족','통','인','p','t','모','두','알','미','포기','단','망','박스','쌍','켤레']);

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

const OBSERVATION_RECEIPT_REASONS = new Set([
  'promotion_observation_outside_period', 'promotion_observation_validity_unconfirmed',
]);

export function isObservationReceiptEligible(offer = {}) {
  return (offer?.observation_receipt_eligible ?? offer?.observationReceiptEligible) !== false
    && !OBSERVATION_RECEIPT_REASONS.has(offer?.observation_receipt_reason ?? offer?.observationReceiptReason);
}

function hasPurchaseCountRule(offer = {}) {
  const conditions = offer?.promotion_conditions || offer?.promotionConditions || {};
  return Number(conditions.buy_quantity) > 0 && Number(conditions.free_quantity) > 0
    || Number(offer?.minimum_quantity ?? offer?.minimumQuantity) > 1;
}

export function getOfferAmountLabel(offer = {}, ordinaryLabel = '관측 표시가') {
  if (hasPurchaseCountRule(offer)) return '출처 조건 계산 금액';
  const conditions = offer.promotion_conditions || offer.promotionConditions || {};
  return conditions.source_condition_kind === 'source_public_base_quote' && conditions.source_base_quote_only === true
    ? '원문 기본 판매가' : ordinaryLabel;
}

function quantityComparisonHeld(offer) {
  return !isObservationReceiptEligible(offer)
    || Boolean(offer?.quantity_comparison_reason || offer?.quantityComparisonReason);
}

function homogeneousMeasure(offer = {}) {
  if (!offer) return null;
  const purpose = (offer.quantity_basis ?? offer.quantityBasis) === 'reviewed_homogeneous_contents'
    && (offer.scalar_basis ?? offer.scalarBasis) === 'one_complete_declared_vector_not_piece_count'
    && (offer.received_package_count_scope ?? offer.receivedPackageCountScope) === 'complete_declared_vector';
  const quantity = offer.pricing_measure_quantity ?? offer.pricingMeasureQuantity;
  const unit = offer.pricing_measure_unit ?? offer.pricingMeasureUnit;
  return purpose && !quantityComparisonHeld(offer)
    && (offer.pricing_measure_basis ?? offer.pricingMeasureBasis) === 'reviewed_homogeneous_contents'
    && Number.isFinite(quantity) && quantity > 0 && ['g', 'ml', '매'].includes(unit)
    ? { quantity, unit } : null;
}

function linearMeasure(offer = {}) {
  const quantity = offer.pricing_measure_quantity ?? offer.pricingMeasureQuantity;
  const total = offer.total_quantity ?? offer.totalQuantity;
  const repetitions = offer.received_package_count ?? offer.receivedPackageCount;
  return !quantityComparisonHeld(offer)
    && (offer.quantity_basis ?? offer.quantityBasis) === 'reviewed_declared_linear_contents'
    && (offer.scalar_basis ?? offer.scalarBasis) === 'declared_linear_contents_not_physical_dimensions'
    && (offer.received_package_count_scope ?? offer.receivedPackageCountScope) === 'declared_linear_package_repetitions'
    && (offer.pricing_measure_basis ?? offer.pricingMeasureBasis) === 'reviewed_declared_linear_contents'
    && (offer.pricing_measure_unit ?? offer.pricingMeasureUnit) === 'm'
    && (offer.quantity_unit ?? offer.quantityUnit) === 'm'
    && Number.isFinite(quantity) && quantity > 0 && quantity === total
    && Number.isInteger(repetitions) && repetitions > 0
    ? { quantity, repetitions } : null;
}

function normalizeHistoryEntry(entry) {
  const price = toNumber(firstDefined(entry.price, entry.current_price, entry.sale_price, entry.amount));
  if (!price) return null;
  return {
    ...entry,
    variantId: entry.variant_id,
    listingId: entry.listing_id,
    offerId: entry.id,
    offerState: entry.offer_state,
    currentEligible: entry.current_eligible,
    comparablePrice: entry.comparable_price,
    quantityComparisonReason: entry.quantity_comparison_reason ?? null,
    observationReceiptEligible: entry.observation_receipt_eligible,
    observationReceiptReason: entry.observation_receipt_reason,
    date: firstDefined(entry.date, entry.observed_at, entry.created_at, entry.crawled_at, entry.updated_at, ''),
    price,
    source: firstDefined(entry.source_name, entry.store_name, entry.source, entry.store, ''),
    sourceUrl: firstDefined(entry.source_url, entry.url, ''),
    unit: firstDefined(entry.display_unit, entry.unit, ''),
    observedAt: firstDefined(entry.observed_at, entry.crawled_at, entry.recorded_at, ''),
    recordKind: firstDefined(entry.record_kind, ''),
    publicationKind: firstDefined(entry.publication_kind, ''),
    priceObservationOnly: Boolean(entry.price_observation_only),
    hasDiscountMetadata: Boolean(entry.has_discount_metadata),
    recordLabel: firstDefined(entry.record_label, ''),
    claimStatusLabel: firstDefined(entry.claim_status_label, ''),
  };
}

export function getOfferUnitPrice(offer = {}, components = []) {
  if (quantityComparisonHeld(offer)) return null;
  if (components.some(component => component.quantity == null || component.unit == null || component.count == null)) return null;
  if (!offer || offer.comparable_price == null || toNumber(offer.comparable_price) <= 0) return null;
  const measured = homogeneousMeasure(offer);
  const homogeneousPurpose = offer.quantity_basis === 'reviewed_homogeneous_contents';
  if (toNumber(offer.per_100g) > 0 && (!homogeneousPurpose || measured?.unit === 'g')) return { price: offer.per_100g, unit: '100g' };
  if (toNumber(offer.per_100ml) > 0 && (!homogeneousPurpose || measured?.unit === 'ml')) return { price: offer.per_100ml, unit: '100ml' };
  if (toNumber(offer.per_100m) > 0 && linearMeasure(offer)) return { price: offer.per_100m, unit: '100m' };
  if (COUNT_UNITS.has(offer.quantity_unit) && toNumber(offer.total_quantity) > 0 && toNumber(offer.per_item) > 0) return { price: offer.per_item, unit: `1${offer.quantity_unit}` };
  return null;
}

function normalizeOffer(entry) {
  // A listed/total amount can remain known while the promotion is unresolved.
  // An explicit null comparable_price must never become a comparable quote.
  const normalized = Object.hasOwn(entry, 'comparable_price');
  if (!isObservationReceiptEligible(entry) || entry.current_eligible === false || (entry.offer_state && entry.offer_state !== 'active')) return null;
  const price = normalized
    ? toNumber(entry.comparable_price)
    : toNumber(firstDefined(entry.price, entry.current_price, entry.sale, entry.sale_price, entry.item_price));
  if (price <= 0) return null;
  const originalPrice = toNumber(firstDefined(entry.original_price, entry.origPrice, entry.orig, entry.regular_price));
  const unitPrice = normalized ? getOfferUnitPrice(entry, entry.quantity_components || []) : null;
  return {
    sourceName: firstDefined(entry.source_name, entry.store_name, entry.source, entry.store, entry.martName, '출처'),
    sourceType: firstDefined(entry.source_type, entry.type, entry.channel, ''),
    title: firstDefined(entry.title, entry.source_title, entry.variant_name, entry.name, entry.item_name, ''),
    price,
    originalPrice,
    discount: toNumber(firstDefined(entry.discount_rate, entry.discount, entry.disc, entry.discountRate)),
    unitPrice: normalized ? unitPrice?.price ?? null : firstDefined(entry.standard_unit_price, entry.unit_price, entry.unitPrice, ''),
    unit: normalized ? unitPrice?.unit ?? null : firstDefined(entry.standard_unit, entry.unit, entry.spec, ''),
    totalPrice: normalized ? entry.total_price : price,
    totalQuantity: normalized ? entry.total_quantity : null,
    quantityUnit: normalized ? entry.quantity_unit : null,
    quantityComparisonReason: entry.quantity_comparison_reason ?? null,
    observationReceiptEligible: entry.observation_receipt_eligible,
    observationReceiptReason: entry.observation_receipt_reason,
    quantityBasis: entry.quantity_basis,
    scalarBasis: entry.scalar_basis,
    receivedPackageCountScope: entry.received_package_count_scope,
    quantityComponents: entry.quantity_components,
    pricingMeasureQuantity: entry.pricing_measure_quantity,
    pricingMeasureUnit: entry.pricing_measure_unit,
    pricingMeasureBasis: entry.pricing_measure_basis,
    variantId: entry.variant_id,
    listingId: entry.listing_id,
    offerId: entry.id,
    listedPrice: entry.listed_price,
    receivedPackageCount: entry.received_package_count,
    bundleCount: entry.bundle_count,
    minimumQuantity: entry.minimum_quantity,
    membershipRequired: entry.membership_required,
    couponRequired: entry.coupon_required,
    promotionCondition: entry.promotion_condition,
    promotionConditions: entry.promotion_conditions,
    period: firstDefined(entry.period, entry.validity_period, entry.valid_until, ''),
    url: firstDefined(entry.source_url, entry.detail_url, entry.detailUrl, entry.url, entry.link, ''),
    trust: firstDefined(entry.trust_label, entry.confidence, entry.confidence_label, ''),
  };
}

function variantOffers(variant = {}) {
  return (variant?.listings || []).flatMap((listing) => {
    const offer = listing.offers?.[0];
    return offer ? [{ ...offer, source: listing.source, source_url: listing.url,
      title: listing.title, variant_id: variant.id, listing_id: listing.id, quantity_components: variant.quantity_components }] : [];
  });
}

export function getVariantBestOffer(variant) {
  return variantOffers(variant).map(normalizeOffer).filter(Boolean)
    .sort((a, b) => a.unit && a.unit === b.unit && a.unitPrice != null && b.unitPrice != null
      ? a.unitPrice - b.unitPrice : 0)[0] || null;
}

function conditionKey(value) {
  if (value == null) return 'null';
  if (Array.isArray(value)) return JSON.stringify(value.map(conditionKey));
  if (typeof value === 'object') return JSON.stringify(Object.keys(value).sort().map(key => [key, conditionKey(value[key])]));
  return JSON.stringify(value);
}

function sameHistoricalReceipt(row, reference) {
  return reference && !quantityComparisonHeld(row) && !quantityComparisonHeld(reference)
    && row.total_quantity > 0 && reference.total_quantity > 0
    && (['g', 'ml'].includes(row.quantity_unit) || COUNT_UNITS.has(row.quantity_unit)
      || (linearMeasure(row) && linearMeasure(reference)
        && row.variant_id && row.variant_id === reference.variant_id))
    && row.total_quantity === reference.total_quantity && row.quantity_unit === reference.quantity_unit
    && row.received_package_count > 0 && row.received_package_count === reference.received_package_count
    && ['minimum_quantity', 'membership_required', 'coupon_required', 'promotion_condition', 'promotion_conditions',
      'quantity_basis', 'scalar_basis', 'received_package_count_scope', 'quantity_components',
      'pricing_measure_quantity', 'pricing_measure_unit', 'pricing_measure_basis']
      .every(field => conditionKey(row[field]) === conditionKey(reference[field]));
}

export function getObservedOfferPriceText(offer = {}, amount = offer?.listed_price) {
  if ((typeof amount !== 'number' && typeof amount !== 'string')
    || (typeof amount === 'string' && !/^(?:\d+(?:\.\d+)?|\.\d+)$/.test(amount.trim()))
    || !Number.isFinite(Number(amount)) || Number(amount) < 0) return '미확인';
  const conditions = offer?.promotion_conditions || {};
  const sourceQuote = conditions.source_condition_kind === 'source_quote_purchase_conditions_unverified';
  if (sourceQuote && Number(amount) === 0) return '미확인';
  const currencyUnknown = sourceQuote && ((Object.hasOwn(conditions, 'source_quote_currency')
    && conditions.source_quote_currency === null) || conditions.currency_unconfirmed === true
    || conditions.source_quote_currency_unconfirmed === true);
  const value = Number(amount).toLocaleString('ko-KR');
  return currencyUnknown ? `${value} (통화 미명시)` : `${value}원`;
}

export function getCatalogObservationDescription(product = {}, options = {}) {
  const description = typeof product.description === 'string' ? product.description : '';
  const catalog = Boolean(product.public_product_id || Object.hasOwn(product, 'best_offer')
    || (typeof product.id === 'string' && product.id.startsWith('prod-')));
  // Only the catalog search producer's generated summary is replaced. Native
  // source descriptions and other result namespaces retain their own wording.
  if (!catalog || !/(^|\/\s*)(?:비교 가능한 )?(?:현재가|관측 조건 비교금액)(?:\s|$)/.test(description)) return description;
  if (Object.hasOwn(options, 'offer')) {
    const offer = options.offer;
    const stamp = offer?.crawled_at || offer?.observed_at;
    const observedAt = typeof stamp === 'string' && Number.isFinite(Date.parse(stamp)) ? stamp : '미확인';
    return `출처 표시 가격 ${getObservedOfferPriceText(offer)} · 관측 시점 ${observedAt}`;
  }
  return `${description.replace('현재가', '관측 조건 비교금액')} · 관측 시점 미확인`;
}

export function getConditionalOfferConditionText(offer = {}) {
  const conditions = offer.promotion_conditions || {};
  const publicBaseQuote = conditions.source_condition_kind === 'source_public_base_quote'
    && conditions.source_base_quote_only === true && conditions.payable_price_unconfirmed === false;
  if (publicBaseQuote || (conditions.source_condition_kind === 'source_quote_purchase_conditions_unverified'
    && conditions.payable_price_unconfirmed === true)) {
    const positiveCount = value => Number.isInteger(value) && value > 0;
    const coupons = conditions.source_coupon_declarations || {};
    const couponRows = [coupons.couponInfo, ...(Array.isArray(coupons.couponList) ? coupons.couponList : [])]
      .filter(row => row && typeof row === 'object');
    const seenCoupons = new Set();
    const couponTexts = couponRows.flatMap(row => {
      const key = JSON.stringify([row.manageCouponNm, row.displayCouponNm, row.purchaseMin, row.discount,
        row.discountType, row.issueStartDt, row.issueEndDt]);
      if (seenCoupons.has(key)) return [];
      seenCoupons.add(key);
      return [[
        `출처 쿠폰: ${row.manageCouponNm || row.displayCouponNm || '이름 미명시'}`,
        typeof row.purchaseMin === 'number' && row.purchaseMin > 0
          ? `구매금액 기준 표기 ${row.purchaseMin.toLocaleString('ko-KR')}` : null,
        typeof row.discount === 'number' && row.discount > 0
          ? `할인값 표기 ${row.discount.toLocaleString('ko-KR')}` : null,
        row.issueStartDt || row.issueEndDt
          ? `출처 발급 기간 ${row.issueStartDt || '시작 미명시'} ~ ${row.issueEndDt || '종료 미명시'}` : null,
        '쿠폰 자격·실제 적용 미확인',
      ].filter(Boolean).join(' · ')];
    });
    const limit = conditions.source_purchase_limit || {};
    return [
      publicBaseQuote ? '출처 기본 표시가격 관측 (쿠폰 할인 전)' : '출처 표시가격 관측',
      typeof conditions.source_promotion_period_text === 'string' && conditions.source_promotion_period_text.trim()
        ? `출처 표시 행사기간 ${conditions.source_promotion_period_text.trim()} · 시간대/경계 미확인` : null,
      positiveCount(conditions.source_minimum_purchase_quantity)
        ? `출처 주문 최소 ${conditions.source_minimum_purchase_quantity}개 · 판매 묶음 수량 아님`
        : '최소구매 수량·총지출 미확인',
      positiveCount(conditions.source_maximum_order_quantity)
        ? `출처 주문 수량 상한 ${conditions.source_maximum_order_quantity}개 · 재고·할인 한도 아님` : null,
      positiveCount(conditions.source_maximum_purchase_quantity)
        ? `출처 구매 수량 한도 ${conditions.source_maximum_purchase_quantity}개 · 판매 묶음 수량 아님` : null,
      limit.purchaseLimitYn === 'Y' && typeof limit.itemPurchaseLimitMessage === 'string' && limit.itemPurchaseLimitMessage.trim()
        ? `출처 구매 한도: ${limit.itemPurchaseLimitMessage}` : null,
      positiveCount(conditions.source_required_product_quantity)
        ? `선택 상품 ${conditions.source_required_product_quantity}개 조건 · 같은 상품 수령량 미확인` : null,
      positiveCount(conditions.source_free_quantity)
        ? `선택 상품 중 ${conditions.source_free_quantity}개 무료 조건 · 무료 상품·금액 미확인` : null,
      conditions.selected_product_scope_unconfirmed === true ? '적용 상품 구성 미확인' : null,
      conditions.membership_eligibility_unconfirmed === true ? '회원 자격 미확인' : null,
      conditions.source_public_flag_values_unrecoverable === true ? '출처 구매 제한 정보 일부 미확인' : null,
      ...couponTexts,
      conditions.coupon_application_unconfirmed === true || !Object.hasOwn(conditions, 'coupon_application_unconfirmed')
        ? '쿠폰 자격·적용 미확인' : null,
      publicBaseQuote
        ? '기본 표시가격·내용량 기준 계산 · 쿠폰 할인·배송비 미포함 · 실제 결제 금액 미확인'
        : '총지출·실제 결제 금액 미확인',
    ].filter(Boolean).join(' · ');
  }
  if (['basket_spend_won_discount', 'basket_spend_percent_discount'].includes(conditions.source_condition_kind)
    && conditions.payable_price_unconfirmed === true) {
    const threshold = conditions.source_spend_threshold_won;
    const amountText = conditions.source_threshold_amount_text
      || (typeof threshold === 'number' && Number.isFinite(threshold) && threshold > 0
        ? `${threshold.toLocaleString('ko-KR')}원` : null);
    const thresholdText = amountText
      ? `출처 구매 금액 조건 ${amountText}${conditions.source_threshold_marker === '이상' ? ' 이상' : conditions.source_threshold_marker === '↑' ? '↑' : ''}`
      : '구매 금액 기준 미확인';
    return [
      '구매 금액 조건부 관측',
      thresholdText,
      conditions.source_threshold_marker === '↑' || conditions.threshold_equality_unconfirmed === true
        ? '기준 금액과 같을 때 적용 여부 미확인' : null,
      conditions.source_scope_text ? `출처 행사 범위: ${conditions.source_scope_text}` : null,
      conditions.source_program_name ? `출처 프로그램: ${conditions.source_program_name}` : null,
      conditions.source_payment_card_text ? `출처 카드 조건: ${conditions.source_payment_card_text} · 카드 이용 자격 미확인` : null,
      conditions.conditional_discount_won > 0 ? `조건부 ${conditions.conditional_discount_won.toLocaleString('ko-KR')}원 할인` : null,
      conditions.conditional_discount_percent > 0 ? `조건부 ${conditions.conditional_discount_percent}% 할인` : null,
      '이용 자격 미확인',
      '적용 상품 구성·금액 배분 미확인',
      '구매 금액 계산 기준 미확인',
      conditions.benefit_cap == null ? '할인 한도 미확인' : `출처 할인 한도 ${conditions.benefit_cap}`,
      conditions.discount_calculation_basis == null ? '할인 계산 기준 미확인' : `출처 할인 계산 기준 ${conditions.discount_calculation_basis}`,
      conditions.source_application_text ? `출처 안내: ${conditions.source_application_text}` : '적용 시점·방법 미확인',
      '실제 적용 미확인',
      '실제 결제 금액 미확인',
    ].filter(Boolean).join(' · ');
  }
  if (conditions.source_condition_kind === 'named_program_percentage_discount' && conditions.payable_price_unconfirmed === true) {
    return [
      `${conditions.source_program_name || '지원 할인 행사'} 조건부 관측`,
      conditions.conditional_discount_percent > 0 ? `조건부 ${conditions.conditional_discount_percent}% 할인` : '할인율 미확인',
      '이용 자격 미확인',
      conditions.benefit_cap == null ? '할인 한도 미확인' : `출처 할인 한도 ${conditions.benefit_cap}`,
      conditions.discount_calculation_basis == null ? '할인 계산 기준 미확인' : `출처 할인 계산 기준 ${conditions.discount_calculation_basis}`,
      conditions.source_application_text ? `출처 안내: ${conditions.source_application_text}` : '적용 시점·방법 미확인',
      '실제 적용 미확인',
      '실제 결제 금액 미확인',
    ].join(' · ');
  }
  if (conditions.basket_selection_required !== true || conditions.payable_price_unconfirmed !== true) return '';
  const positiveCount = value => typeof value === 'number' && Number.isInteger(value) && value > 0;
  const limit = conditions.source_purchase_limit || {};
  const period = conditions.source_event_period || {};
  const intervals = Array.isArray(conditions.source_selection_price_intervals)
    ? conditions.source_selection_price_intervals.filter(point => positiveCount(point.thresholdQty)
      && typeof point.changeAmount === 'number' && Number.isFinite(point.changeAmount) && point.changeAmount > 0) : [];
  const intervalText = point => `${point.thresholdQty}개 조건 ${point.changeAmount.toLocaleString('ko-KR')}원`;
  return [
    '조건부 행사 관측',
    conditions.required_selection_quantity > 0 ? `선택 상품 ${conditions.required_selection_quantity}개 조건 · 같은 상품 수령량 미확인` : '선택 상품 구성 미확인',
    conditions.conditional_free_quantity > 0 ? `선택 상품 중 ${conditions.conditional_free_quantity}개 무료 조건 · 무료 상품·금액 미확인` : null,
    conditions.conditional_discount_percent > 0 ? `조건부 ${conditions.conditional_discount_percent}% 할인 · 적용 미확인` : null,
    conditions.conditional_basket_total_won > 0 ? `선택 묶음 총액 ${conditions.conditional_basket_total_won.toLocaleString('ko-KR')}원 조건 · 적용 상품 구성 미확인` : null,
    conditions.conditional_discount_won > 0 ? `조건부 ${conditions.conditional_discount_won.toLocaleString('ko-KR')}원 할인 · 적용 미확인` : null,
    positiveCount(conditions.source_event_maximum_quantity)
      ? `출처 행사 적용 수량 상한 ${conditions.source_event_maximum_quantity}개 · 재고·판매 묶음 수량 아님` : null,
    positiveCount(conditions.source_order_minimum_quantity)
      ? `출처 주문 최소 ${conditions.source_order_minimum_quantity}개 · 행사 선택 수량과 별도` : null,
    limit.purchaseLimitYn === 'Y' && typeof limit.itemPurchaseLimitMessage === 'string' && limit.itemPurchaseLimitMessage.trim()
      ? `출처 구매 한도: ${limit.itemPurchaseLimitMessage}` : null,
    period.start_date || period.end_date
      ? `출처 행사 기간 ${period.start_date || '시작일 미확인'} ~ ${period.end_date || '종료일 미확인'} · 현재 이용 자격 미확인` : null,
    intervals.length ? `출처 단계별 조건: ${intervalText(intervals[0])}${intervals.length > 1
      ? ` … ${intervalText(intervals.at(-1))} (${intervals.length}개 명시 단계)` : ''} · 적용 상품 구성 미확인` : null,
    conditions.coupon_application_unconfirmed === true ? '쿠폰 자격·적용 미확인' : null,
    '실제 결제 금액 미확인',
  ].filter(Boolean).join(' · ');
}

export function getOfferReceiptText(offer = {}, { receiptValid = true, components = offer.quantity_components || [], observed = false } = {}) {
  if (!isObservationReceiptEligible(offer)) return [
    '관측 당시 행사 적용 미확인 · 행사 계산 수령량 미확인',
    offer.valid_from || offer.valid_to
      ? `출처 행사 기간 ${offer.valid_from || '시작일 미확인'} ~ ${offer.valid_to || '종료일 미확인'}` : null,
    ...getQuantityComponentTexts(components),
  ].filter(Boolean).join(' · ');
  if (['measured_inner_scope_unresolved','independent_count_scope_unresolved'].includes(offer.quantity_comparison_reason))
    return '원문 내용량의 각량·전체 범위 미확인';
  const declaredVector = (['reviewed_source_component_vector_v1', 'reviewed_homogeneous_contents'].includes(offer.quantity_basis)
    && offer.scalar_basis === 'one_complete_declared_vector_not_piece_count'
    && offer.received_package_count_scope === 'complete_declared_vector')
    || components.some(component => component.count == null);
  const prefix = `${observed ? '관측 ' : ''}${hasPurchaseCountRule(offer) ? '출처 조건 계산: ' : ''}`;
  const linear = receiptValid ? linearMeasure(offer) : null;
  if (offer.quantity_unit === 'm' || offer.quantity_basis === 'reviewed_declared_linear_contents') return [
    linear ? `${prefix}선형 내용량 ${linear.quantity}m` : `${prefix}선형 판매 내용량 검증 미확인`,
    linear ? `${prefix}선택 선형 구성 ×${linear.repetitions}` : null,
    '물리 패키지 수량 미확인',
  ].filter(Boolean).join(' · ');
  if (declaredVector) return [
    receiptValid && offer.total_quantity > 0 && offer.quantity_unit === '세트'
      ? `${prefix}선언된 전체 구성 ×${offer.total_quantity}` : `${prefix}수령 구성 미확인`,
    '물리 패키지 수량 미확인',
    receiptValid && homogeneousMeasure(offer)
      ? `${prefix}동종 구성 총 내용량 ${homogeneousMeasure(offer).quantity}${homogeneousMeasure(offer).unit}` : null,
    ...getQuantityComponentTexts(components),
  ].filter(Boolean).join(' · ');
  const purchaseRuleUnits = offer.received_package_count_scope === 'source_purchase_rule_package_repetitions';
  const packageCountLabel = purchaseRuleUnits ? '구매 조건 수령 단위' : '수령 패키지';
  const countKnown = receiptValid && (purchaseRuleUnits
    ? Number.isInteger(offer.received_package_count) && offer.received_package_count > 0
    : offer.received_package_count != null);
  return [
    receiptValid && offer.total_quantity > 0 && offer.quantity_unit ? `${prefix}수령 ${offer.total_quantity}${offer.quantity_unit}` : '판매 수량 미확인',
    countKnown ? `${prefix}${packageCountLabel} ${offer.received_package_count}` : `${packageCountLabel} 미확인`,
    purchaseRuleUnits ? '물리 패키지 수량 미확인' : null,
  ].filter(Boolean).join(' · ');
}

export function getOfferConditionText(offer = {}, { receiptValid = true } = {}) {
  const held = !isObservationReceiptEligible(offer);
  const rule = held ? '출처 행사 규칙: ' : '';
  return [
    getOfferReceiptText(offer, { receiptValid }),
    offer.minimum_quantity != null ? `${rule}최소 구매 ${offer.minimum_quantity}` : '최소 구매 미확인',
    (offer.promotion_condition || offer.promotion_conditions?.condition_text)
      ? `${rule}${offer.promotion_condition || offer.promotion_conditions?.condition_text}` : null,
    getConditionalOfferConditionText(offer),
    offer.promotion_conditions?.buy_quantity != null ? `${rule}구매 ${offer.promotion_conditions.buy_quantity}` : null,
    offer.promotion_conditions?.free_quantity != null ? `${rule}추가 증정 ${offer.promotion_conditions.free_quantity}` : null,
    offer.membership_required === true ? '회원 필요' : offer.membership_required === false ? '회원 제한 없음' : '회원 조건 미확인',
    offer.coupon_required === true ? '쿠폰 필요' : offer.coupon_required === false ? '쿠폰 필요 없음' : '쿠폰 조건 미확인',
  ].filter(Boolean).join(' · ');
}

export function isSavedReceiptValid(item = {}) {
  const id = item.product_id ?? item.product_catalog_id;
  const normalizedSelection = typeof id === 'string' && id.startsWith('prod-')
    && Boolean(item.variant_id || item.listing_id || item.offer_id);
  const quote = item.offer_context || item.quoted_offer || {};
  const unprovedLinear = quote.quantity_unit === 'm' && !linearMeasure(quote);
  if (!isObservationReceiptEligible(quote) || OBSERVATION_RECEIPT_REASONS.has(item.saved_receipt_reason)) return false;
  return !normalizedSelection || (item.saved_receipt_valid === true && !unprovedLinear);
}

export function getSavedReceiptHoldText(item = {}) {
  if (isSavedReceiptValid(item)) return null;
  const reason = ({
    selected_specification_revised: '저장 당시 규격이 변경되었습니다',
    selection_context_missing: '저장된 규격 정보를 확인할 수 없습니다',
    catalog_unavailable: '카탈로그를 확인할 수 없습니다',
    promotion_observation_outside_period: '관측 당시 행사 기간 밖의 계산 거래입니다',
    promotion_observation_validity_unconfirmed: '관측 당시 행사 기간 적용을 확인할 수 없습니다',
  })[item.saved_receipt_reason || (item.offer_context || item.quoted_offer)?.observation_receipt_reason]
    || '저장된 수령 구성을 확인할 수 없습니다';
  return `${reason} · 수령량·단위가 판정 보류 · 규격 확인·다시 선택 필요`;
}

export function getSavedOfferConditionText(item = {}, offer = item.offer_context || {}) {
  const context = OBSERVATION_RECEIPT_REASONS.has(item.saved_receipt_reason)
    ? { ...offer, observation_receipt_eligible: false, observation_receipt_reason: item.saved_receipt_reason } : offer;
  return getOfferConditionText(context, { receiptValid: isSavedReceiptValid(item) });
}

// Cart money is a saved source observation, not a fresh checkout quote. Known
// aggregate contents remain observable when only their recipe allocation is
// held, but a revised saved specification must never regain its old unit basis.
export function getCartQuotePresentation(item = {}) {
  const selected = Boolean(item.variant_id || item.listing_id || item.offer_id);
  const quote = item.offer_context || item.quoted_offer || {};
  const conditions = quote.promotion_conditions || {};
  const validReceipt = isSavedReceiptValid(item);
  const observationHeld = !isObservationReceiptEligible(quote)
    || OBSERVATION_RECEIPT_REASONS.has(item.saved_receipt_reason);
  const allocationReasons = ['contents_identity_and_allocation_unverified',
    'heterogeneous_contents_allocation_unverified'];
  const comparisonReason = quote.quantity_comparison_reason
    || (allocationReasons.includes(item.saved_receipt_reason) ? item.saved_receipt_reason : null);
  const allocationHeld = allocationReasons.includes(comparisonReason);
  const knownObservation = !observationHeld && (validReceipt || (allocationHeld
    && (!item.saved_receipt_reason || item.saved_receipt_reason === comparisonReason)));
  const end = quote.valid_to && String(quote.valid_to).replace(' ', 'T');
  const expiry = end ? Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(end) ? end : `${end}Z`) : NaN;
  const today = new Date().toISOString().slice(0, 10);
  const expired = quote.availability_reason === 'expired'
    || (end?.length === 10 ? today > end : Number.isFinite(expiry) && expiry < Date.now());
  const start = quote.valid_from && String(quote.valid_from).replace(' ', 'T');
  const startsAt = start ? Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(start) ? start : `${start}Z`) : NaN;
  const notStarted = ['not_started', 'not_yet_valid'].includes(quote.availability_reason)
    || (start?.length === 10 ? today < start : Number.isFinite(startsAt) && startsAt > Date.now());
  const benefitUnknown = quote.membership_required !== false || quote.coupon_required !== false;
  const confirmedPurchase = selected && validReceipt && !expired
    && !notStarted && quote.is_latest !== false && quote.validity_eligible !== false
    && !quote.availability_reason
    && quote.current_eligible === true && !benefitUnknown
    && Number(quote.minimum_quantity) > 0
    && !conditions.payable_price_unconfirmed && !conditions.program_eligibility_unconfirmed
    && !conditions.discount_application_unconfirmed
    && Number(quote.total_price) > 0 && Number(quote.total_price) === Number(item.price);
  const historical = expired || quote.is_latest === false;
  const statusText = !selected ? null : [
    observationHeld ? '저장된 행사 계산 금액 · 관측 당시 적용 미확인' : null,
    observationHeld && quote.listed_price != null ? `출처 표시 가격 ${getObservedOfferPriceText(quote)}` : null,
    historical ? (observationHeld ? '판매 기간 종료 · 과거 표시 가격 관측'
      : expired ? '판매 기간 종료 · 과거 가격 관측' : '과거 가격 관측') : null,
    notStarted ? '판매 시작 전 가격 관측' : null,
    !confirmedPurchase ? '현재 결제 금액·구매 가능 여부 미확인' : null,
    benefitUnknown ? '회원·쿠폰 이용 조건 미확인' : null,
  ].filter(Boolean).join(' · ');
  const observedReceipt = selected && !validReceipt && knownObservation
    ? getOfferReceiptText(quote, { observed: true }) : null;
  return {
    selected, confirmedPurchase, statusText, observedReceipt,
    amountLabel: !selected ? '저장 금액' : observationHeld ? '저장된 행사 계산 금액 (적용 미확인)'
      : hasPurchaseCountRule(quote) ? '저장된 출처 조건 계산 금액'
        : confirmedPurchase ? '확인된 구매 금액' : historical ? '과거 관측 금액' : '저장 관측 금액',
    canDisplayUnitPrice: validReceipt && !comparisonReason,
  };
}

export function getQuantityComponentTexts(components = []) {
  return components.map(component => [
    component.identity || '구성품 이름 미확인',
    component.quantity > 0 && component.unit ? `${component.quantity}${component.unit}` : '측정 내용량 미확인',
    component.count > 0 ? `수량 ${component.count}` : '수량 미확인',
  ].join(' · '));
}

export function getWishlistHoldText(reason) {
  return ({
    selected_specification_revised: '저장 당시 규격이 변경되었습니다',
    selection_required: '규격·판매처 선택 필요',
    selection_context_missing: '저장된 규격·판매처 선택 필요',
    selected_listing_unavailable: '선택한 판매처 거래 없음',
    selected_product_unavailable: '선택한 상품 정보 미확인',
    latest_quote_unavailable: '최신 관측 가격 미확인',
    quote_unavailable: '현재 판매 여부 미확인',
    price_unconfirmed: '현재 거래 금액 미확인',
    receipt_basis_unknown: '수령 구성 미확인',
    receipt_conditions_changed: '저장 당시 구성·이용 조건과 다름',
    membership_or_coupon_unverified: '회원·쿠폰 이용 조건 미확인',
    basket_selection_unconfirmed: '행사 대상 장바구니 선택·상품 구성 미확인',
    conditional_payment_unconfirmed: '출처 조건은 보존됨 · 실제 결제 금액 미확인',
    not_started: '판매 시작 전',
    not_yet_valid: '판매 시작 전',
    validity_unconfirmed: '판매 기간 확인 필요',
    eligibility_unverified: '회원·쿠폰·최소 구매 등 이용 조건 미확인',
    expired: '판매 기간 종료',
    catalog_unavailable: '카탈로그 확인 불가',
  })[reason] || '비교 가능한 현재 거래 미확인';
}

export function getPriceHistorySummary(product = {}, apiHistory = [], { variantId } = {}) {
  const normalizedCatalog = Boolean(product.public_product_id || Object.hasOwn(product, 'best_offer'));
  const selectedVariant = variantId ?? product.selected_variant_id ?? product.best_offer?.variant_id;
  const rows = asArray(apiHistory, product.price_history, product.priceHistory, product.history, product.priceHistorySummary?.history)
    .map(normalizeHistoryEntry).filter(Boolean);
  const corrections = rows.filter(row => row.observation_kind === 'source_interpretation_correction'
    && row.source_correction_verified === true
    && (!normalizedCatalog || (selectedVariant && row.variantId === selectedVariant)));
  // A reviewed projection reuses its original observation. It is context, not
  // another capture; link only the exact original event across revised variants.
  const originalIds = new Set(corrections.map(row => row.source_correction_lineage?.original_event_id).filter(Boolean));
  const history = rows.filter(row => row.observation_kind !== 'source_interpretation_correction')
    .filter(row => !normalizedCatalog || (selectedVariant && (row.variantId === selectedVariant || originalIds.has(row.offerId))))
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));

  const embedded = normalizedCatalog ? {} : product.price_history_summary || product.priceHistorySummary || {};
  const reference = product.selected_offer || product.best_offer;
  // Prior eligible observations remain valid history even when a newer event
  // makes is_latest/current_eligible false. Their own comparable quote and
  // matching actual receipt/conditions determine statistical compatibility.
  const comparableHistory = normalizedCatalog ? history.filter(row => row.comparablePrice > 0
    && (!row.offerState || row.offerState === 'active') && sameHistoricalReceipt(row, reference)) : history;
  const prices = comparableHistory.map(row => normalizedCatalog ? row.comparablePrice : row.price);
  const min = toNumber(firstDefined(embedded.min, embedded.min_price, embedded.lowest_price), prices.length ? Math.min(...prices) : 0);
  const max = toNumber(firstDefined(embedded.max, embedded.max_price, embedded.highest_price), prices.length ? Math.max(...prices) : 0);
  const avg = toNumber(firstDefined(embedded.avg, embedded.average, embedded.average_price), prices.length ? Math.round(prices.reduce((sum, p) => sum + p, 0) / prices.length) : 0);
  const latest = toNumber(firstDefined(embedded.latest, embedded.latest_price), history.at(-1)?.price || 0);
  const previous = prices.length > 1 ? prices.at(-2) : 0;
  const trend = firstDefined(embedded.trend, latest && previous ? (latest < previous ? 'down' : latest > previous ? 'up' : 'stable') : 'unknown');
  const lastDiscountDate = firstDefined(
    embedded.last_discount_date,
    embedded.lastDiscountDate,
    history.filter((h) => h.hasDiscountMetadata && !h.priceObservationOnly).at(-1)?.date,
    ''
  );

  return {
    history,
    corrections,
    hasData: history.length > 0 || min > 0 || avg > 0 || max > 0,
    sparse: history.length > 0 && history.length < 3,
    count: history.length || toNumber(firstDefined(embedded.count, embedded.reference_count)),
    comparableCount: comparableHistory.length,
    min: normalizedCatalog && !prices.length ? null : min,
    avg: normalizedCatalog && !prices.length ? null : avg,
    max: normalizedCatalog && !prices.length ? null : max,
    latest,
    trend: normalizedCatalog && comparableHistory.length !== history.length ? 'unknown' : trend,
    lastDiscountDate,
  };
}

export function getComparableOffers(product = {}, priceCompare = null) {
  const normalizedProduct = Boolean(Object.hasOwn(product, 'best_offer') || product.public_product_id);
  const raw = asArray(
    normalizedProduct ? (product.variants || []).flatMap(variantOffers) : [],
    product.comparable_offers,
    product.comparableOffers,
    product.offers,
    product.other_sources,
    product.otherStores,
    priceCompare?.other_stores,
    priceCompare?.stores,
    priceCompare?.sources,
    priceCompare?.items,
    priceCompare,
    (product.variants || []).flatMap(variantOffers)
  );
  const offers = raw.map(normalizeOffer).filter(Boolean);
  const p = normalizeProduct(product);

  if (!normalizedProduct && p.price > 0 && !offers.some((o) => o.price === p.price && o.sourceName === (p.storeName || p.sourceType || '출처'))) {
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
  const reference = normalizeOffer(product.best_offer || {}) || (!normalizedProduct ? offers.find(offer => offer.current) : null) || null;
  const sameReceipt = (a, b) => !quantityComparisonHeld(a) && !quantityComparisonHeld(b)
    && a.variantId && a.variantId === b.variantId
    && a.totalQuantity > 0 && b.totalQuantity > 0
    && (['g','ml'].includes(a.quantityUnit) || COUNT_UNITS.has(a.quantityUnit)
      || (linearMeasure(a) && linearMeasure(b)))
    && a.bundleCount > 0 && a.bundleCount === b.bundleCount
    && a.receivedPackageCount > 0 && a.receivedPackageCount === b.receivedPackageCount
    && a.totalQuantity === b.totalQuantity && a.quantityUnit === b.quantityUnit
    && a.minimumQuantity === b.minimumQuantity && a.membershipRequired === b.membershipRequired
    && a.couponRequired === b.couponRequired && a.promotionCondition === b.promotionCondition
    && conditionKey(a.promotionConditions) === conditionKey(b.promotionConditions)
    && ['quantityBasis', 'scalarBasis', 'receivedPackageCountScope', 'quantityComponents',
      'pricingMeasureQuantity', 'pricingMeasureUnit', 'pricingMeasureBasis']
      .every(field => conditionKey(a[field]) === conditionKey(b[field]));
  return offers.map(offer => {
    // A typed count label alone does not prove equal entitlements or portions.
    // Measured rates retain their existing common dimensional basis.
    const measuredReference = homogeneousMeasure(reference);
    const typedCount = !(measuredReference && ['g', 'ml'].includes(measuredReference.unit)) && (COUNT_UNITS.has(reference?.quantityUnit)
      || (typeof reference?.unit === 'string' && reference.unit.startsWith('1') && COUNT_UNITS.has(reference.unit.slice(1))));
    const sameUnit = !quantityComparisonHeld(reference) && !quantityComparisonHeld(offer)
      && reference?.unit && offer.unit === reference.unit && offer.unitPrice != null && reference.unitPrice != null
      && (!typedCount || sameReceipt(offer, reference));
    const sameSpec = reference && !reference.unit && sameReceipt(offer, reference);
    return { ...offer, current: offer.offerId ? offer.offerId === product.selected_offer_id || offer.offerId === product.best_offer?.id : Boolean(offer.current),
      comparisonValue: sameUnit ? offer.unitPrice : sameSpec ? offer.price : null,
      comparisonBasis: sameUnit ? reference.unit : sameSpec ? '선택 규격·수령 구성' : null };
  }).sort((a, b) => (a.comparisonValue ?? Infinity) - (b.comparisonValue ?? Infinity)).slice(0, 6);
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
  const normalizedCatalog = Boolean(product.public_product_id || Object.hasOwn(product, 'best_offer'));
  const trust = normalizedCatalog ? {} : priceTrust || product.price_trust || product.priceTrust || product.trust || {};
  const rationale = normalizedCatalog ? '' : firstDefined(trust.rationale, trust.reason, product.hotdeal_rationale, product.rationale, '');
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
  if (normalizedCatalog) {
    return { label: current <= low ? '동일 조건 관측 최저' : current < avg ? '동일 조건 평균보다 낮음' : '동일 조건 관측 참고', tone: 'neutral',
      copy: '선택 규격의 같은 수령·행사 조건 관측에 한정한 비교입니다. 회원·쿠폰 조건 미확인 항목은 원문에서 확인하세요.' };
  }
  if (p.priceObservationOnly && low && current <= low) {
    return { label: '저가 관측', tone: 'good', copy: '수집된 가격 이력 기준 낮은 가격입니다. 출처 할인 표기는 없으니 다른 판매처와 함께 확인하세요.' };
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
  const normalizedCatalog = Boolean(product.public_product_id || Object.hasOwn(product, 'best_offer'));
  // Source declarations survive even when this selected quote cannot provide
  // a comparable/current transaction. Never borrow another group's offer.
  const selectedSource = normalizedCatalog ? getProductSelection(product)?.offer : null;
  const sourceText = value => typeof value === 'string' && value.trim() ? value.trim() : '';
  const sourceStart = sourceText(selectedSource?.valid_from);
  const sourceEnd = sourceText(selectedSource?.valid_to);
  const sourcePeriod = sourceStart || sourceEnd
    ? `출처 행사 기간 ${sourceStart || '시작일 미확인'} ~ ${sourceEnd || '종료일 미확인'}` : '';
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
      period: normalizedCatalog
        ? `${selectedSource?.availability_reason === 'expired' ? '판매 기간 종료 · ' : ''}${sourcePeriod}`
        : firstDefined(normalized.period, product.validity_period, product.valid_until, ''),
      conditionText: selectedSource ? getOfferConditionText(selectedSource) : '',
      unitPrice: firstDefined(normalized.standardUnitPrice, product.unit_price, ''),
      unit: normalized.standardUnit,
    },
  };
}
