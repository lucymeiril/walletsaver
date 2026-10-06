const NUMBER_RE = /^\d+$/;

export function asNumericId(value) {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) return value;
  if (typeof value === 'string' && NUMBER_RE.test(value)) return Number(value);
  return null;
}

function firstDefined(...values) {
  return values.find((v) => v !== undefined && v !== null && v !== '');
}

function toNumber(value, fallback = 0) {
  if (value === undefined || value === null || value === '') return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function toKeywords(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === 'string') {
    return value.split(/[,\s#]+/).map((v) => v.trim()).filter(Boolean);
  }
  return [];
}

function stableHash(value) {
  const str = String(value || '');
  let hash = 0;
  for (let i = 0; i < str.length; i += 1) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

function slugPart(value, fallback = 'item') {
  return String(value || fallback)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9가-힣]+/gi, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48) || fallback;
}

export function normalizeProduct(product = {}) {
  const explicitProductId = firstDefined(product.public_product_id, product.product_id, product.productId);
  const looksLikeSavedListItem = explicitProductId == null
    && (
      product.item_name !== undefined
      || product.item_price !== undefined
      || product.price_at_add !== undefined
      || product.current_price !== undefined
      || product.cart_id !== undefined
    );
  const looksLikeHotdeal = Boolean(
    product.hotdeal_id !== undefined
    || product.type === 'hotdeal'
    || product.source_type === 'hotdeal'
    || (
      product.title !== undefined
      && (
        product.votes_hot !== undefined
        || product.votes_not !== undefined
        || product.time !== undefined
        || product.comments !== undefined
      )
    )
  );
  const inferredProductId = (!looksLikeSavedListItem && !looksLikeHotdeal) ? product.id : undefined;
  const rawId = firstDefined(explicitProductId, inferredProductId);
  const sourceIdentityId = firstDefined(product.hotdeal_id, product.id, rawId);
  const numericProductId = asNumericId(rawId);
  const catalogProductId = rawId != null && String(rawId).trim() ? String(rawId) : null;
  const name = firstDefined(
    product.name,
    product.canonical_name,
    product.product_name,
    product.title,
    product.source_title,
    product.item_name,
    product.itemName,
    '상품명 없음',
  );
  const normalizedCatalog = Boolean(product.public_product_id || Object.hasOwn(product, 'best_offer'));
  const price = toNumber(firstDefined(
    normalizedCatalog ? product.price : product.sale,
    normalizedCatalog ? product.cur : product.price,
    product.current_price,
    product.item_price,
    product.itemPrice,
    product.sale_price,
  ));
  const originalPrice = toNumber(firstDefined(
    product.orig,
    product.original_price,
    product.origPrice,
    product.regular_price,
  ));
  const priceObservationOnly = Boolean(product.price_observation_only);
  const hasDiscountMetadata = Boolean(product.has_discount_metadata)
    || (!priceObservationOnly && originalPrice > price && toNumber(firstDefined(product.disc, product.discount_pct, product.discount, product.discountRate)) > 0);
  const storeKey = firstDefined(product.store_key, product.martKey, product.source_key, product.source, '');
  const storeName = firstDefined(
    product.store_name,
    product.store,
    product.martName,
    product.source_name,
    product.sourceLabel,
    product.source,
    '',
  );
  const category = firstDefined(product.category_path, product.category, product.category_name, product.category_id, '');
  const sourceType = firstDefined(product.type, product.source_type, product.sourceType, looksLikeHotdeal ? 'hotdeal' : (product.martKey ? 'mart' : ''));
  const sourceUrl = firstDefined(product.source_url, product.detail_url, product.detailUrl, product.link, product.url, '');
  const image = firstDefined(product.img, product.image_url, product.image, product.item_image_url, product.thumbnail, '');
  const sourceTitle = firstDefined(product.source_title, product.offer_title, product.title, '');
  const stableSource = firstDefined(sourceType, storeKey, storeName, product.source, 'item');
  const stableBasis = [
    stableSource,
    sourceUrl,
    sourceTitle,
    !numericProductId ? sourceIdentityId : '',
    name,
    storeName,
    storeKey,
    firstDefined(product.unit, product.spec, ''),
  ].filter(Boolean).join('|');
  const stableExternalId = `external:${slugPart(stableSource)}:${stableHash(stableBasis)}`;
  const selected = getProductSelection(product);
  const variantId = product.selected_variant_id ?? product.variant_id ?? selected?.variant.id;
  const listingId = product.selected_listing_id ?? product.listing_id ?? selected?.listing.id;
  // A watch follows a source and spec across price observations; its saved
  // event remains evidence, rather than becoming part of the watch identity.
  const favoriteId = catalogProductId ? `product:${catalogProductId}${variantId && listingId
    ? `:${encodeURIComponent(variantId)}:${encodeURIComponent(listingId)}` : ''}` : stableExternalId;

  return {
    raw: product,
    rawId,
    numericProductId,
    catalogProductId,
    stableId: catalogProductId ? `product:${catalogProductId}` : stableExternalId,
    favoriteId,
    name,
    price,
    originalPrice: hasDiscountMetadata ? originalPrice : 0,
    discount: hasDiscountMetadata ? toNumber(firstDefined(product.disc, product.discount_pct, product.discount, product.discountRate)) : 0,
    recordKind: firstDefined(product.record_kind, ''),
    publicationKind: firstDefined(product.publication_kind, ''),
    priceObservationOnly,
    discountClaimStatus: firstDefined(product.discount_claim_status, ''),
    claimBasis: firstDefined(product.claim_basis, ''),
    hasDiscountMetadata,
    recordLabel: firstDefined(product.record_label, priceObservationOnly ? '관측 가격' : ''),
    claimStatusLabel: firstDefined(product.claim_status_label, ''),
    image,
    storeName,
    storeKey,
    category,
    categoryId: firstDefined(product.category_id, product.categoryId, null),
    unit: firstDefined(product.unit, product.spec, ''),
    brand: firstDefined(product.brand, ''),
    sourceUrl,
    eventType: firstDefined(product.event, product.event_name, ''),
    period: firstDefined(product.period, ''),
    keywords: toKeywords(firstDefined(product.keywords, product.keyword, product.tags, [])),
    sourceTitle,
    description: firstDefined(product.description, product.content, product.summary, ''),
    unitPriceDisplay: firstDefined(product.unit_price_display, product.attributes?.unit_price_display, product.offer_raw_data?.unit_price_display, ''),
    standardUnitPrice: firstDefined(product.standard_unit_price, product.unit_price, null),
    standardUnit: firstDefined(product.standard_unit, null),
    sourceType,
    priceHistory: firstDefined(product.price_history, product.priceHistory, product.history, []),
    comparableOffers: firstDefined(product.comparable_offers, product.comparableOffers, product.offers, product.other_sources, []),
    priceTrust: firstDefined(product.price_trust, product.priceTrust, product.trust, null),
    community: {
      hotVotes: toNumber(firstDefined(product.hotVotes, product.hot_votes, product.votes_hot)),
      coldVotes: toNumber(firstDefined(product.coldVotes, product.cold_votes, product.votes_not)),
      comments: toNumber(product.comments),
      views: toNumber(product.views),
    },
    quantity: toNumber(product.quantity, 1) || 1,
  };
}

export function getProductSelection(product, selection = {}) {
  const variantId = selection.variantId ?? product.selected_variant_id ?? product.variant_id;
  const listingId = selection.listingId ?? product.selected_listing_id ?? product.listing_id;
  const offerId = selection.offerId ?? product.selected_offer_id ?? product.offer_id;
  const choices = (product.variants || []).flatMap(variant => (variant.listings || []).flatMap(listing => {
    const offer = listing.offers?.[0];
    return offer ? [{ variant, listing, offer }] : [];
  }));
  if (variantId || listingId || offerId) {
    return choices.find(row => (!variantId || row.variant.id === variantId)
      && (!listingId || row.listing.id === listingId) && (!offerId || row.offer.id === offerId)) || null;
  }
  if (['selection_context_missing', 'selection_required'].includes(product.comparison_reason)) return null;
  return choices.find(row => row.offer.id && row.offer.id === product.best_offer?.id)
    || (choices.length === 1 ? choices[0] : null);
}

export function buildProductShareUrl(product, selection = {}, origin = window.location.origin) {
  const identity = normalizeProduct(product);
  const id = product.public_product_id ?? identity.catalogProductId ?? identity.numericProductId;
  if (!id) throw new Error('공유할 상품을 확인할 수 없습니다');
  const url = new URL(`/price/${encodeURIComponent(id)}`, origin);
  if (product.public_product_id || Object.hasOwn(product, 'best_offer')) {
    const chosen = getProductSelection(product, selection);
    if (!chosen?.variant.id || !chosen?.listing.id || !chosen?.offer.id)
      throw new Error('공유할 규격·판매처·관측을 다시 선택해주세요');
    url.searchParams.set('variant', chosen.variant.id);
    url.searchParams.set('listing', chosen.listing.id);
    url.searchParams.set('offer', chosen.offer.id);
  }
  return url.href;
}

function selectedVariantDisplayUnit(variant) {
  // Keep literal approximate/range/composition descriptions ahead of scalar facts.
  if (typeof variant.display_unit === 'string' && variant.display_unit.trim()) return variant.display_unit;
  const { package_quantity: amount, package_unit: unit, bundle_count: bundles } = variant;
  if (variant.quantity_components?.length || !['g', 'ml'].includes(unit)
    || typeof amount !== 'number' || !Number.isFinite(amount) || amount <= 0
    || !Number.isInteger(bundles) || bundles <= 0) return '';
  return `${amount}${unit}${bundles > 1 ? `×${bundles}` : ''}`;
}

export function selectProductOffer(product, selection = {}) {
  const chosen = getProductSelection(product, selection);
  if (!chosen) return product.variant_id || product.selected_variant_id
    || ['selection_context_missing', 'selection_required'].includes(product.comparison_reason)
    ? { ...product, best_offer: null, price: null, cur: null, current_price: null, item_price: null,
      unit: product.offer_context?.display_unit || product.unit || '' } : product;
  const { variant, listing, offer } = chosen;
  const comparable = offer.current_eligible !== false && (!offer.offer_state || offer.offer_state === 'active')
    ? (Number(offer.comparable_price) > 0 ? offer.comparable_price : null) : null;
  const selectedOffer = variant.quantity_components?.length
    ? { ...offer, quantity_components: variant.quantity_components } : offer;
  return { ...product, selected_variant_id: variant.id, selected_listing_id: listing.id,
    selected_offer_id: offer.id, selected_offer: selectedOffer,
    best_offer: comparable != null ? { ...selectedOffer, variant_id: variant.id, listing_id: listing.id,
      source: listing.source, source_url: listing.url } : null,
    price: comparable, cur: comparable, original_price: offer.original_price ?? null, orig: null, origPrice: null,
    discount_rate: offer.discount_rate ?? null, discount_pct: offer.discount_rate != null ? offer.discount_rate * 100 : null,
    disc: null, discount: null, has_discount_metadata: offer.original_price != null && offer.discount_rate != null,
    unit: selectedVariantDisplayUnit(variant),
    store_name: listing.source, source: listing.source, source_url: listing.url, source_title: listing.title };
}

export function cartIdentity(item) {
  const id = item.product_catalog_id ?? item.product_id;
  const selected = [item.variant_id, item.listing_id, item.offer_id];
  return id != null ? `product:${id}${selected.some(Boolean) ? ':' + selected.map(value => encodeURIComponent(value || '')).join(':') : ''}`
    : item.local_id || item.id;
}

function payloadQuote(product, selection = {}) {
  const normalized = normalizeProduct(product);
  const catalog = Boolean(product.public_product_id || Object.hasOwn(product, 'best_offer'));
  const chosen = getProductSelection(product, selection);
  if (chosen) {
    const { variant, listing, offer } = chosen;
    const price = firstDefined(offer.total_price, offer.listed_price);
    const knownPrice = price != null && Number.isFinite(Number(price)) && Number(price) > 0;
    const comparable = offer.current_eligible !== false && (!offer.offer_state || offer.offer_state === 'active')
      ? (Number(offer.comparable_price) > 0 ? offer.comparable_price : null) : null;
    return { normalized: normalizeProduct({ ...product, price, cur: price, store_name: listing.source,
      source_url: listing.url, source_title: listing.title, unit: selectedVariantDisplayUnit(variant) }),
      knownPrice, currentPrice: comparable, selection: chosen };
  }
  if (selection.variantId || selection.listingId || selection.offerId || product.selected_variant_id || product.variant_id) {
    return { normalized, knownPrice: false, currentPrice: null };
  }
  if (catalog && (product.variants || []).some(variant => variant.listings?.some(listing => listing.offers?.length))) {
    return { normalized, knownPrice: false, currentPrice: null };
  }
  if (catalog && normalized.price <= 0) {
    const quotes = (product.variants || []).flatMap((variant) => (variant.listings || []).flatMap((listing) => {
      const offer = listing.offers?.[0];
      return offer?.listed_price != null && Number.isFinite(Number(offer.listed_price)) && Number(offer.listed_price) > 0
        ? [{ listing, price: Number(offer.listed_price) }] : [];
    }));
    if (quotes.length !== 1) return { normalized, knownPrice: false, currentPrice: null };
    const { listing, price } = quotes[0];
    return { normalized: normalizeProduct({ ...product, price, store_name: listing.source,
      source_url: listing.url, source_title: listing.title }), knownPrice: true, currentPrice: null };
  }
  const explicitPrice = firstDefined(product.sale, product.price, product.current_price,
    product.item_price, product.itemPrice, product.sale_price);
  return { normalized, knownPrice: explicitPrice != null && (!catalog || normalized.price > 0), currentPrice: explicitPrice != null ? normalized.price : null };
}

function payloadCatalogId(product, normalized) {
  if (normalized.numericProductId) return normalized.numericProductId;
  const explicit = firstDefined(product.public_product_id, product.product_id, product.productId);
  return explicit != null || product.type === 'product' || normalized.catalogProductId?.startsWith('prod-')
    ? normalized.catalogProductId : null;
}

export function buildCartPayload(product, selection = {}) {
  const { normalized: p, knownPrice, selection: chosen } = payloadQuote(product, selection);
  if (!knownPrice) throw new Error('상품 표시 가격이 확인되지 않아 장바구니 금액을 저장할 수 없습니다');
  if (chosen && (product.public_product_id || Object.hasOwn(product, 'best_offer'))
    && !(Number(chosen.offer.total_price) > 0)) throw new Error('실제 거래 금액이 확인되지 않아 장바구니 금액을 저장할 수 없습니다');
  const catalogId = payloadCatalogId(product, p);
  return {
    ...(catalogId ? { product_id: catalogId } : {}),
    ...(chosen?.variant.id && chosen?.listing.id && chosen?.offer.id ? { variant_id: chosen.variant.id, listing_id: chosen.listing.id,
      offer_id: chosen.offer.id, quoted_offer: { ...chosen.offer,
        ...(chosen.variant.quantity_components?.length ? { quantity_components: chosen.variant.quantity_components } : {}) } } : {}),
    local_id: chosen?.variant.id && chosen?.listing.id && chosen?.offer.id ? cartIdentity({ product_id: catalogId, variant_id: chosen.variant.id,
      listing_id: chosen.listing.id, offer_id: chosen.offer.id }) : p.favoriteId,
    item_name: p.name,
    name: p.name,
    item_price: p.price,
    price: p.price,
    item_image_url: p.image,
    image: p.image,
    store_name: p.storeName,
    store_key: p.storeKey,
    source_url: p.sourceUrl,
    original_price: p.originalPrice,
    discount_rate: p.discount,
    category: p.category,
    unit: p.unit,
    period: p.period,
    event_name: p.eventType,
    source_type: p.sourceType,
    source_title: p.sourceTitle,
    record_kind: p.recordKind,
    publication_kind: p.publicationKind,
    price_observation_only: p.priceObservationOnly,
    has_discount_metadata: p.hasDiscountMetadata,
    discount_claim_status: p.discountClaimStatus,
    claim_basis: p.claimBasis,
    record_label: p.recordLabel,
    claim_status_label: p.claimStatusLabel,
    description: p.description,
    standard_unit_price: p.standardUnitPrice,
    standard_unit: p.standardUnit,
    quantity: p.quantity,
  };
}

export function buildWishlistPayload(product) {
  const { normalized: p, knownPrice, currentPrice, selection: chosen } = payloadQuote(product);
  const catalogId = payloadCatalogId(product, p);
  return {
    ...(catalogId ? { product_id: catalogId } : {}),
    ...(chosen?.variant.id && chosen?.listing.id && chosen?.offer.id ? {
      variant_id: chosen.variant.id, listing_id: chosen.listing.id, offer_id: chosen.offer.id,
    } : {}),
    local_id: p.favoriteId,
    item_name: p.name,
    item_image_url: p.image,
    store_name: p.storeName,
    category: p.category,
    price_at_add: knownPrice ? p.price : null,
    current_price: currentPrice,
    item_price: knownPrice ? p.price : null,
    source_url: p.sourceUrl,
    original_price: p.originalPrice,
    discount_rate: p.discount,
    unit: p.unit,
    period: p.period,
    event_name: p.eventType,
    source_type: p.sourceType,
    source_title: p.sourceTitle,
    record_kind: p.recordKind,
    publication_kind: p.publicationKind,
    price_observation_only: p.priceObservationOnly,
    has_discount_metadata: p.hasDiscountMetadata,
    discount_claim_status: p.discountClaimStatus,
    claim_basis: p.claimBasis,
    record_label: p.recordLabel,
    claim_status_label: p.claimStatusLabel,
    description: p.description,
    standard_unit_price: p.standardUnitPrice,
    standard_unit: p.standardUnit,
    price_history: p.priceHistory,
    comparable_offers: p.comparableOffers,
    price_trust: p.priceTrust,
    hotVotes: p.community.hotVotes,
    coldVotes: p.community.coldVotes,
    comments: p.community.comments,
    views: p.community.views,
  };
}
