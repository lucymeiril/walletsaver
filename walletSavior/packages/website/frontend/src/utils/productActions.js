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
  const explicitProductId = firstDefined(product.product_id, product.productId);
  const looksLikeSavedListItem = explicitProductId == null
    && (
      product.item_name !== undefined
      || product.item_price !== undefined
      || product.price_at_add !== undefined
      || product.current_price !== undefined
      || product.cart_id !== undefined
    );
  const rawId = firstDefined(explicitProductId, looksLikeSavedListItem ? undefined : product.id);
  const numericProductId = asNumericId(rawId);
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
  const price = toNumber(firstDefined(
    product.sale,
    product.price,
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
  const sourceType = firstDefined(product.type, product.source_type, product.sourceType, product.martKey ? 'mart' : '');
  const sourceUrl = firstDefined(product.source_url, product.detail_url, product.detailUrl, product.link, product.url, '');
  const image = firstDefined(product.img, product.image_url, product.image, product.item_image_url, product.thumbnail, '');
  const sourceTitle = firstDefined(product.source_title, product.offer_title, product.title, '');
  const stableSource = firstDefined(sourceType, storeKey, storeName, product.source, 'item');
  const stableBasis = [
    stableSource,
    sourceUrl,
    sourceTitle,
    rawId && !numericProductId ? rawId : '',
    name,
    storeName,
    storeKey,
    firstDefined(product.unit, product.spec, ''),
  ].filter(Boolean).join('|');
  const stableExternalId = `external:${slugPart(stableSource)}:${stableHash(stableBasis)}`;

  return {
    raw: product,
    rawId,
    numericProductId,
    stableId: numericProductId ? `product:${numericProductId}` : stableExternalId,
    favoriteId: numericProductId ? `product:${numericProductId}` : stableExternalId,
    name,
    price,
    originalPrice,
    discount: toNumber(firstDefined(product.disc, product.discount_pct, product.discount, product.discountRate)),
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
    standardUnitPrice: firstDefined(product.standard_unit_price, product.unit_price, null),
    standardUnit: firstDefined(product.standard_unit, '100g'),
    sourceType,
    quantity: toNumber(product.quantity, 1) || 1,
  };
}

export function buildCartPayload(product) {
  const p = normalizeProduct(product);
  return {
    ...(p.numericProductId ? { product_id: p.numericProductId } : {}),
    local_id: p.favoriteId,
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
    quantity: p.quantity,
  };
}

export function buildWishlistPayload(product) {
  const p = normalizeProduct(product);
  return {
    ...(p.numericProductId ? { product_id: p.numericProductId } : {}),
    local_id: p.favoriteId,
    item_name: p.name,
    item_image_url: p.image,
    store_name: p.storeName,
    category: p.category,
    price_at_add: p.price,
    current_price: p.price,
    item_price: p.price,
    source_url: p.sourceUrl,
    original_price: p.originalPrice,
    discount_rate: p.discount,
    unit: p.unit,
  };
}
