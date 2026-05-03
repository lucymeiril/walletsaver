"""WalletSavior 자동 카테고리 분류 엔진.

크롤링된 상품명을 파싱하고, 543개 카테고리 트리에서
최적의 카테고리를 매칭하여 신뢰도와 함께 반환한다.

설계 원칙:
  - 분류 실패가 **절대** 데이터 저장을 막아서는 안 된다.
  - 항상 CategorizeResult 를 반환하며, 최악의 경우 confidence=0.
  - 외부 NLP 라이브러리 없이 순수 정규식 + 사전 매칭만 사용.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────

@dataclass
class ParseResult:
    original_name: str
    cleaned_name: str
    keywords: list[str]
    attributes: dict
    brand: Optional[str]
    bracket_info: list[str]


@dataclass
class CategoryMatch:
    category_id: str
    score: float
    match_type: str  # keyword_direct, synonym, mapping, category_name, source_context
    matched_token: str


@dataclass
class CategorizeResult:
    category_id: Optional[str]
    confidence: float
    auto_assigned: bool
    attributes: dict
    candidates: list[tuple[str, float]]
    parsed_keywords: list[str]
    brand: Optional[str]
    parse_result: ParseResult


# ──────────────────────────────────────────────
# Static data imports (lazy-loaded)
# ──────────────────────────────────────────────

_CATEGORIES: list[dict] | None = None
_KEYWORDS: list[dict] | None = None
_PRODUCT_MAPPINGS: list[dict] | None = None
_CATEGORY_MAP: dict[str, dict] | None = None

# ── 사전 빌드 인덱스 (핫패스 최적화) ──
# keyword word → category_id (O(1) 직접 매칭)
_KW_WORD_TO_CAT: dict[str, str] | None = None
# synonym → (category_id, keyword_word) (O(1) 동의어 매칭)
_KW_SYN_TO_CAT: dict[str, tuple[str, str]] | None = None
# mapping name → mapping dict (O(1))
_MAPPING_BY_NAME: dict[str, dict] | None = None
# mapping alias → mapping dict (O(1))
_MAPPING_BY_ALIAS: dict[str, dict] | None = None
# category name → list of (cat_id, depth) (카테고리명 매칭)
_CATNAME_TO_IDS: dict[str, list[tuple[str, int]]] | None = None


def _load_data():
    """카테고리/키워드/매핑 데이터를 한 번만 로드하고 인덱스를 빌드."""
    global _CATEGORIES, _KEYWORDS, _PRODUCT_MAPPINGS, _CATEGORY_MAP
    global _KW_WORD_TO_CAT, _KW_SYN_TO_CAT
    global _MAPPING_BY_NAME, _MAPPING_BY_ALIAS, _CATNAME_TO_IDS
    if _CATEGORIES is not None:
        return
    try:
        from category_data.categories import CATEGORIES
        from category_data.keywords import KEYWORDS
        from category_data.mappings import PRODUCT_MAPPINGS
        _CATEGORIES = CATEGORIES
        _KEYWORDS = KEYWORDS
        _PRODUCT_MAPPINGS = PRODUCT_MAPPINGS
        _CATEGORY_MAP = {c["id"]: c for c in CATEGORIES}

        # ── 인덱스 빌드: 선형 스캔을 O(1) 해시 조회로 대체 ──
        _KW_WORD_TO_CAT = {}
        _KW_SYN_TO_CAT = {}
        for entry in KEYWORDS:
            cat_id = entry.get("category_id")
            if cat_id:
                _KW_WORD_TO_CAT[entry["word"]] = cat_id
                for syn in entry.get("synonyms", []):
                    if syn not in _KW_SYN_TO_CAT:
                        _KW_SYN_TO_CAT[syn] = (cat_id, entry["word"])

        _MAPPING_BY_NAME = {pm["name"]: pm for pm in PRODUCT_MAPPINGS}
        _MAPPING_BY_ALIAS = {}
        for pm in PRODUCT_MAPPINGS:
            for alias in pm.get("aliases", []):
                if alias not in _MAPPING_BY_ALIAS:
                    _MAPPING_BY_ALIAS[alias] = pm

        _CATNAME_TO_IDS = {}
        for cat in CATEGORIES:
            name = cat["name"]
            _CATNAME_TO_IDS.setdefault(name, []).append(
                (cat["id"], cat.get("depth", 0))
            )

    except ImportError:
        _CATEGORIES = []
        _KEYWORDS = []
        _PRODUCT_MAPPINGS = []
        _CATEGORY_MAP = {}
        _KW_WORD_TO_CAT = {}
        _KW_SYN_TO_CAT = {}
        _MAPPING_BY_NAME = {}
        _MAPPING_BY_ALIAS = {}
        _CATNAME_TO_IDS = {}


# ──────────────────────────────────────────────
# Brand dictionaries
# ──────────────────────────────────────────────

KNOWN_BRANDS: dict[str, str] = {
    # 이마트 PB
    "보먹돼": "emart_pb", "YBD": "emart_pb", "황금돼지": "emart_pb",
    "피코크": "emart_pb", "노브랜드": "emart_pb", "일품포크": "emart_pb",
    # 롯데마트 PB
    "L'TABLE": "lotte_pb", "초이스엘": "lotte_pb", "요리하다": "lotte_pb",
    # 홈플러스 PB
    "심플러스": "homeplus_pb", "홈플러스시그니처": "homeplus_pb",
    # 식품 브랜드
    "하림": "food", "풀무원": "food", "비비고": "food", "CJ": "food",
    "오뚜기": "food", "농심": "food", "삼양": "food", "빙그레": "food",
    "매일": "food", "서울우유": "food", "남양": "food", "파스퇴르": "food",
    "맥심": "food", "동원": "food", "사조": "food", "진주햄": "food",
    "롯데햄": "food", "대상": "food", "청정원": "food",
    # 해외 브랜드
    "Kirkland": "foreign", "커클랜드": "foreign", "코스트코": "foreign",
    # 비식품
    "드라이빗": "non_food", "무인양품": "non_food",
    # 축산 브랜드
    "공육사": "meat", "한돈": "meat",
}

BRAND_CATEGORY_HINTS: dict[str, str] = {
    "빙그레": "dairy",
    "서울우유": "dairy",
    "매일": "dairy",
    "남양": "dairy",
    "파스퇴르": "dairy",
    "하림": "livestock.chicken",
    "동원": "seafood",
    "사조": "seafood",
    "농심": "processed.noodle",
    "삼양": "processed.noodle",
    "오뚜기": "processed",
    "풀무원": "processed",
    "비비고": "processed",
    "맥심": "beverage.coffee",
    "드라이빗": "beauty",
}

FOOD_CATEGORIES = frozenset({
    "agriculture", "livestock", "seafood", "processed",
    "dairy", "beverage", "alcohol", "health", "snack",
})


# ──────────────────────────────────────────────
# Attribute extraction patterns
# ──────────────────────────────────────────────

ATTRIBUTE_PATTERNS = {
    "storage": re.compile(r"(냉장|냉동|상온|실온|해동)"),
    "origin": re.compile(
        r"(국산|국내산|한우|한돈|수입|수입산|미국산|호주산|스페인산|캐나다산|제주|제주산|제주직송)"
    ),
    "grade": re.compile(r"(1\+\+|1\+|1등급|2등급|3등급|특등급|특|상)"),
    "weight": re.compile(
        r"(\d+(?:\.\d+)?)\s*(g|kg|ml|l|리터)", re.IGNORECASE
    ),
    "count": re.compile(
        r"(\d+)\s*(개|입|팩|봉|세트|T|매|장|병|캔|포)", re.IGNORECASE
    ),
    "usage": re.compile(
        r"(구이|수육|볶음|탕|스테이크|샤브|불고기|보쌈|찜|전골|국거리|다짐|편육|장조림)\s?용?"
    ),
}

# noise patterns
_NOISE_RE = re.compile(
    r"[★♥♡☆●◆▶▷◀◁♨※✔✓✗✘⚡️🔥💯🎉❤️⭐🌟✨💥💫🎊🎁🔔📢❗‼️]+|"
    r"\[(?:행사|특가|인기|할인|무료배송|SALE|sale|이벤트|추천|베스트|HOT|hot)\]"
)

_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
_PAREN_RE = re.compile(r"\(([^)]+)\)")
_PROMO_TOKEN_RE = re.compile(r"^(행사|특가|인기|할인|SALE|sale|HOT|hot)$")

# promotional standalone tokens
_PROMO_STANDALONE_RE = re.compile(
    r"\b(특가|행사|인기|할인|무료배송|SALE|HOT)\b", re.IGNORECASE
)

# 이모지 제거 — 한 번만 컴파일 (per-call 컴파일 방지)
_EMOJI_RE = re.compile(
    r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
    r"\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF"
    r"\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
    r"\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF]+"
)


# ──────────────────────────────────────────────
# Step 1: Remove noise
# ──────────────────────────────────────────────

def _remove_noise(name: str) -> str:
    """Remove emojis, stars, promotional bracket tags."""
    result = _NOISE_RE.sub("", name)
    # Remove emoji unicode ranges (모듈 레벨 컴파일된 정규식 사용)
    result = _EMOJI_RE.sub("", result)
    result = _PROMO_STANDALONE_RE.sub("", result)
    return result.strip()


# ──────────────────────────────────────────────
# Step 2: Extract bracket/parenthesis info
# ──────────────────────────────────────────────

def _extract_brackets(name: str) -> tuple[list[str], str]:
    """Extract [bracket] and (paren) info. Returns (info_list, cleaned_name)."""
    bracket_info: list[str] = []
    cleaned = name

    for m in _BRACKET_RE.finditer(name):
        content = m.group(1).strip()
        if not _PROMO_TOKEN_RE.match(content):
            bracket_info.append(content)

    for m in _PAREN_RE.finditer(name):
        content = m.group(1).strip()
        if content:
            bracket_info.append(content)

    cleaned = _BRACKET_RE.sub(" ", cleaned)
    cleaned = _PAREN_RE.sub(" ", cleaned)
    return bracket_info, cleaned.strip()


# ──────────────────────────────────────────────
# Step 3: Split separators (모듈 레벨 정규식)
# ──────────────────────────────────────────────

_SEPARATOR_RE = re.compile(r"[/·|+\s]+")

def _split_separators(text: str) -> list[str]:
    """Split on /, ·, |, + and whitespace. Returns non-empty tokens."""
    parts = _SEPARATOR_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


# ──────────────────────────────────────────────
# Step 4: Extract structured attributes
# ──────────────────────────────────────────────

def extract_attributes(name: str) -> dict:
    """Extract structured attributes (storage, origin, grade, weight, count, usage) from name."""
    attrs: dict = {}
    try:
        m = ATTRIBUTE_PATTERNS["storage"].search(name)
        if m:
            attrs["storage"] = m.group(1)

        m = ATTRIBUTE_PATTERNS["origin"].search(name)
        if m:
            val = m.group(1)
            if val in ("제주직송",):
                attrs["origin"] = "제주"
            else:
                attrs["origin"] = val

        m = ATTRIBUTE_PATTERNS["grade"].search(name)
        if m:
            attrs["grade"] = m.group(1)

        m = ATTRIBUTE_PATTERNS["weight"].search(name)
        if m:
            value = float(m.group(1))
            unit = m.group(2).lower()
            if unit == "kg":
                attrs["weight_g"] = int(value * 1000)
            elif unit in ("g",):
                attrs["weight_g"] = int(value)
            elif unit in ("l", "리터"):
                attrs["weight_ml"] = int(value * 1000)
            elif unit == "ml":
                attrs["weight_ml"] = int(value)
            attrs["weight_unit"] = m.group(2)

        m = ATTRIBUTE_PATTERNS["count"].search(name)
        if m:
            attrs["count"] = int(m.group(1))
            attrs["count_unit"] = m.group(2)

        m = ATTRIBUTE_PATTERNS["usage"].search(name)
        if m:
            usage = m.group(1)
            attrs["usage"] = usage

    except Exception:
        pass
    return attrs


# 속성 토큰 판별용 정규식 (모듈 레벨 컴파일)
_ATTR_WEIGHT_RE = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:g|kg|ml|l|리터|개|입|팩|봉|세트|T|매|장|병|캔|포)$",
    re.IGNORECASE,
)
_ATTR_STORAGE_RE = re.compile(r"^(?:냉장|냉동|상온|실온|해동)$")
_ATTR_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


def _is_attribute_token(token: str) -> bool:
    """Check if a token is purely an attribute (weight, count, etc.)."""
    if _ATTR_WEIGHT_RE.match(token):
        return True
    if _ATTR_STORAGE_RE.match(token):
        return True
    if _ATTR_NUMBER_RE.match(token):
        return True
    return False


# ──────────────────────────────────────────────
# Step 5: Brand filtering
# ──────────────────────────────────────────────

# 브랜드명 대소문자 무관 조회용 인덱스 (모듈 레벨에서 한 번 빌드)
_BRAND_UPPER_MAP: dict[str, str] = {name.upper(): name for name in KNOWN_BRANDS}


def _identify_brand(tokens: list[str]) -> tuple[Optional[str], list[str]]:
    """Identify and remove brand from tokens. O(1) dict lookup."""
    brand_found: Optional[str] = None
    remaining: list[str] = []

    for token in tokens:
        if not brand_found:
            # 정확 매칭 또는 대소문자 무관 매칭 — O(1)
            if token in KNOWN_BRANDS:
                brand_found = token
                continue
            upper_match = _BRAND_UPPER_MAP.get(token.upper())
            if upper_match:
                brand_found = upper_match
                continue
        remaining.append(token)

    return brand_found, remaining


# ──────────────────────────────────────────────
# Step 6: Extract pure product keywords
# ──────────────────────────────────────────────

_USAGE_SUFFIX_RE = re.compile(r"용$")


def _extract_keywords(tokens: list[str]) -> list[str]:
    """Filter out attribute-only tokens, return pure product keywords."""
    keywords: list[str] = []
    for token in tokens:
        if not token:
            continue
        if _is_attribute_token(token):
            continue
        # remove usage suffix (e.g., "수육용" → "수육" already captured in attributes)
        cleaned = _USAGE_SUFFIX_RE.sub("", token)
        if cleaned and len(cleaned) >= 1:
            keywords.append(cleaned)
    return keywords


# ──────────────────────────────────────────────
# Full parsing pipeline
# ──────────────────────────────────────────────

# 브래킷 내 필터링 패턴 (모듈 레벨 컴파일)
_SOURCE_TAG_RE = re.compile(r"^(GS25|이마트|롯데마트|홈플러스|코스트코|쿠팡|SSG)$")
_BRACKET_ATTR_RE = re.compile(r"^(냉장|냉동|상온|실온|해동)$")
_BRACKET_ORIGIN_RE = re.compile(r"^(제주직송|국산|수입|수입산)$")


def parse_product_name(name: str) -> ParseResult:
    """6-step parsing pipeline for product names."""
    try:
        if not name or not name.strip():
            return ParseResult(
                original_name=name or "",
                cleaned_name="",
                keywords=[],
                attributes={},
                brand=None,
                bracket_info=[],
            )

        # Step 1: remove noise
        cleaned = _remove_noise(name)

        # Step 2: extract bracket/paren info
        bracket_info, cleaned = _extract_brackets(cleaned)

        # Step 4 (before split): extract attributes from full text
        attrs = extract_attributes(name)

        # Step 3: split separators
        tokens = _split_separators(cleaned)

        # Also tokenize bracket info and add to pool
        bracket_tokens: list[str] = []
        for info in bracket_info:
            # Skip source tags, attribute tags, origin tags (pre-compiled)
            if _SOURCE_TAG_RE.match(info):
                continue
            if _BRACKET_ATTR_RE.match(info):
                continue
            if _BRACKET_ORIGIN_RE.match(info):
                continue
            sub_tokens = _split_separators(info)
            bracket_tokens.extend(sub_tokens)

        all_tokens = tokens + bracket_tokens

        # Step 5: brand filtering
        brand, filtered_tokens = _identify_brand(all_tokens)

        # Step 6: extract keywords
        keywords = _extract_keywords(filtered_tokens)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_keywords: list[str] = []
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                unique_keywords.append(kw)

        return ParseResult(
            original_name=name,
            cleaned_name=cleaned,
            keywords=unique_keywords,
            attributes=attrs,
            brand=brand,
            bracket_info=bracket_info,
        )

    except Exception:
        return ParseResult(
            original_name=name or "",
            cleaned_name=name or "",
            keywords=[],
            attributes={},
            brand=None,
            bracket_info=[],
        )


# ──────────────────────────────────────────────
# Category matching stages
# ──────────────────────────────────────────────

def match_category(keywords: list[str], source: str | None = None) -> list[CategoryMatch]:
    """5-stage matching pipeline. Uses pre-built hash indices for O(1) lookups."""
    _load_data()
    matches: list[CategoryMatch] = []

    if not keywords:
        return matches

    # Stage 1: Exact keyword match — O(1) dict lookup per keyword
    for kw in keywords:
        cat_id = (_KW_WORD_TO_CAT or {}).get(kw)
        if cat_id:
            matches.append(CategoryMatch(
                category_id=cat_id,
                score=0.5,
                match_type="keyword_direct",
                matched_token=kw,
            ))

    # Stage 2: Synonym match — O(1) exact + partial substring scan
    for kw in keywords:
        # Exact synonym lookup (O(1))
        syn_result = (_KW_SYN_TO_CAT or {}).get(kw)
        if syn_result:
            matches.append(CategoryMatch(
                category_id=syn_result[0],
                score=0.4,
                match_type="synonym",
                matched_token=kw,
            ))
            continue

        # Partial synonym match (substring) — must scan, but only keywords with synonyms
        for entry in _KEYWORDS or []:
            if not entry.get("category_id"):
                continue
            for syn in entry.get("synonyms", []):
                if kw in syn or syn in kw:
                    matches.append(CategoryMatch(
                        category_id=entry["category_id"],
                        score=0.3,
                        match_type="synonym",
                        matched_token=kw,
                    ))
                    break
            else:
                continue
            break

    # Stage 3: Product mappings — O(1) name/alias + partial substring
    seen_mapping_kws: set[tuple[str, str]] = set()
    for kw in keywords:
        # O(1) exact name match
        pm = (_MAPPING_BY_NAME or {}).get(kw)
        if pm:
            for cat_id in pm.get("categories", []):
                key = (kw, cat_id)
                if key not in seen_mapping_kws:
                    seen_mapping_kws.add(key)
                    matches.append(CategoryMatch(
                        category_id=cat_id, score=0.45,
                        match_type="mapping", matched_token=kw,
                    ))
            continue

        # O(1) exact alias match
        pm = (_MAPPING_BY_ALIAS or {}).get(kw)
        if pm:
            for cat_id in pm.get("categories", []):
                key = (kw, cat_id)
                if key not in seen_mapping_kws:
                    seen_mapping_kws.add(key)
                    matches.append(CategoryMatch(
                        category_id=cat_id, score=0.45,
                        match_type="mapping", matched_token=kw,
                    ))
            continue

        # Partial substring match (fallback)
        for mapping in _PRODUCT_MAPPINGS or []:
            mapping_name = mapping["name"]
            mapping_cats = mapping.get("categories", [])
            if not mapping_cats:
                continue
            matched = mapping_name in kw or kw in mapping_name
            if not matched:
                for alias in mapping.get("aliases", []):
                    if alias in kw or kw in alias:
                        matched = True
                        break
            if matched:
                for cat_id in mapping_cats:
                    key = (kw, cat_id)
                    if key not in seen_mapping_kws:
                        seen_mapping_kws.add(key)
                        matches.append(CategoryMatch(
                            category_id=cat_id, score=0.45,
                            match_type="mapping", matched_token=kw,
                        ))

    # Stage 4: Category name substring match — O(1) exact + partial
    for kw in keywords:
        if len(kw) < 2:
            continue
        # Exact category name match (O(1))
        exact_cats = (_CATNAME_TO_IDS or {}).get(kw)
        if exact_cats:
            for cat_id, depth in exact_cats:
                matches.append(CategoryMatch(
                    category_id=cat_id,
                    score=0.3 + depth * 0.1,
                    match_type="category_name",
                    matched_token=kw,
                ))
        # Partial name substring (must scan)
        for cat in _CATEGORIES or []:
            cat_name = cat["name"]
            cat_id = cat["id"]
            depth = cat.get("depth", 0)
            if cat_name == kw:
                continue  # already handled above
            if (len(kw) >= 2 and kw in cat_name) or (len(cat_name) >= 2 and cat_name in kw):
                matches.append(CategoryMatch(
                    category_id=cat_id,
                    score=0.3 + depth * 0.1,
                    match_type="category_name",
                    matched_token=kw,
                ))

    # Stage 5: Source context adjustment
    if source and source.lower() in ("emart", "lotte", "homeplus", "gs25", "coupang"):
        for match in matches:
            major = match.category_id.split(".")[0]
            if major in FOOD_CATEGORIES:
                match.score += 0.1

    return matches


# ──────────────────────────────────────────────
# Disambiguation
# ──────────────────────────────────────────────

def disambiguate(
    candidates: list[CategoryMatch],
    keywords: list[str],
    source: str | None = None,
) -> list[CategoryMatch]:
    """Resolve ambiguous category candidates using co-occurrence and source context."""
    if not candidates:
        return candidates

    # Build per-keyword category lists
    kw_cats: dict[str, list[str]] = {}
    for c in candidates:
        kw_cats.setdefault(c.matched_token, []).append(c.category_id)

    # Find confirmed majors (keywords with only one unique major category)
    confirmed_majors: set[str] = set()
    for token, cats in kw_cats.items():
        majors = set(c.split(".")[0] for c in cats)
        if len(majors) == 1:
            confirmed_majors.update(majors)

    if not confirmed_majors:
        # Use source context if no confirmed majors
        if source and source.lower() in ("emart", "lotte", "homeplus", "gs25", "coupang"):
            confirmed_majors = FOOD_CATEGORIES
        else:
            return candidates

    # Filter: keep candidates whose major category is in confirmed set
    filtered: list[CategoryMatch] = []
    for c in candidates:
        major = c.category_id.split(".")[0]
        if major in confirmed_majors:
            filtered.append(c)

    return filtered if filtered else candidates


# ──────────────────────────────────────────────
# Score aggregation
# ──────────────────────────────────────────────

def _aggregate_scores(
    candidates: list[CategoryMatch],
    keywords: list[str],
) -> dict[str, float]:
    """Aggregate scores per category_id with multi-token bonus.

    Uses a pre-grouped dict to find best score per (category, token) pair
    in O(n) instead of O(n²).
    """
    # 1단계: (category_id, matched_token) 별 최대 점수를 한 번에 계산
    best_per_pair: dict[tuple[str, str], float] = {}
    for c in candidates:
        key = (c.category_id, c.matched_token)
        if key not in best_per_pair or c.score > best_per_pair[key]:
            best_per_pair[key] = c.score

    # 2단계: 카테고리별 점수 합산
    scores: dict[str, float] = {}
    cat_token_count: dict[str, int] = {}
    for (cat_id, _token), best_score in best_per_pair.items():
        scores[cat_id] = scores.get(cat_id, 0.0) + best_score
        cat_token_count[cat_id] = cat_token_count.get(cat_id, 0) + 1

    # Multi-token bonus: +0.15 per additional token matching same category
    for cat_id, count in cat_token_count.items():
        if count > 1:
            scores[cat_id] += 0.15 * (count - 1)

    return scores


# ──────────────────────────────────────────────
# Main entry point (LRU 캐시로 동일 상품명 재계산 방지)
# ──────────────────────────────────────────────

# 내부 캐시 함수 — hashable 인자만 받는다
@functools.lru_cache(maxsize=2048)
def _auto_categorize_cached(product_name: str, source: str | None) -> tuple:
    """캐시 가능한 내부 분류 함수. 결과를 tuple로 반환."""
    return _auto_categorize_impl(product_name, source)


def auto_categorize(product_name: str, source: str | None = None) -> CategorizeResult:
    """Main auto-categorization entry point.

    NEVER raises exceptions. Always returns a CategorizeResult.
    LRU 캐시로 동일 (product_name, source) 쌍의 재계산을 방지.
    """
    cached = _auto_categorize_cached(product_name, source)
    # 캐시된 tuple → CategorizeResult 복원
    return CategorizeResult(*cached)


def _auto_categorize_impl(product_name: str, source: str | None) -> tuple:
    """Internal implementation. Returns tuple matching CategorizeResult fields.

    NEVER raises exceptions.
    """
    _empty_parse = ParseResult(
        original_name=product_name or "",
        cleaned_name="",
        keywords=[],
        attributes={},
        brand=None,
        bracket_info=[],
    )
    _empty_tuple = (None, 0.0, False, {}, [], [], None, _empty_parse)

    try:
        if not product_name or not product_name.strip():
            return _empty_tuple

        # Phase 1: Parse
        parsed = parse_product_name(product_name)

        # Add brand category hints as extra keywords if applicable
        extra_keywords = list(parsed.keywords)
        brand_hint_cat: str | None = None
        if parsed.brand and parsed.brand in BRAND_CATEGORY_HINTS:
            brand_hint_cat = BRAND_CATEGORY_HINTS[parsed.brand]

        # Phase 2: Match
        candidates = match_category(extra_keywords, source)

        # Apply brand category hints: boost candidates matching the hint
        if brand_hint_cat:
            for c in candidates:
                if c.category_id.startswith(brand_hint_cat):
                    c.score += 0.1

            # If no match found from keywords but brand hints exist, add a hint match
            hint_cats = [c for c in candidates if c.category_id.startswith(brand_hint_cat)]
            if not hint_cats:
                _load_data()
                for cat in _CATEGORIES or []:
                    if cat["id"] == brand_hint_cat or cat["id"].startswith(brand_hint_cat + "."):
                        candidates.append(CategoryMatch(
                            category_id=cat["id"],
                            score=0.25,
                            match_type="brand_hint",
                            matched_token=parsed.brand or "",
                        ))
                        break

        # Phase 3: Disambiguate
        if len(set(c.category_id.split(".")[0] for c in candidates)) > 1:
            candidates = disambiguate(candidates, extra_keywords, source)

        # Phase 4: Aggregate scores
        scored = _aggregate_scores(candidates, extra_keywords)

        # Phase 5: Select best
        if not scored:
            return (None, 0.0, False, parsed.attributes, [],
                    parsed.keywords, parsed.brand, parsed)

        # Prefer deeper (more specific) categories when scores are close
        sorted_cats = sorted(scored.items(), key=lambda x: (-x[1], -_get_depth(x[0])))
        best_cat = sorted_cats[0][0]
        confidence = min(sorted_cats[0][1], 1.0)

        top_candidates = [(cat_id, min(s, 1.0)) for cat_id, s in sorted_cats[:5]]

        return (
            best_cat if confidence >= 0.50 else None,
            confidence,
            confidence >= 0.85,
            parsed.attributes,
            top_candidates,
            parsed.keywords,
            parsed.brand,
            parsed,
        )

    except Exception:
        return _empty_tuple


def _get_depth(category_id: str) -> int:
    """Return depth of a category by its ID."""
    _load_data()
    cat = (_CATEGORY_MAP or {}).get(category_id)
    if cat:
        return cat.get("depth", 0)
    return category_id.count(".")


# ──────────────────────────────────────────────
# Fuzzy Korean keyword → category fallback
# ──────────────────────────────────────────────

_KOREAN_KEYWORD_MAP: list[tuple[list[str], str]] = [
    # 축산/돼지
    (["삼겹살", "목살", "돼지고기", "앞다리", "뒷다리", "돼지갈비", "돼지등심", "돼지안심", "보쌈", "족발", "돼지", "돈까스", "돈카츠"], "livestock.pork"),
    # 축산/소
    (["한우", "소고기", "등심", "안심", "차돌박이", "양지", "사태", "갈비", "불고기", "국거리", "척아이롤", "채끝"], "livestock.beef"),
    # 축산/닭
    (["닭가슴살", "닭다리", "닭날개", "닭볶음탕", "통닭", "닭고기", "닭", "치킨텐더", "치킨너겟"], "livestock.chicken"),
    # 과일
    (["사과", "배", "포도", "딸기", "수박", "참외", "복숭아", "자두", "키위", "바나나", "오렌지", "귤", "감", "블루베리", "망고", "체리", "멜론", "레몬", "천혜향", "한라봉"], "agriculture.fruit"),
    # 채소/엽채
    (["배추", "시금치", "상추", "양배추", "깻잎", "부추", "대파", "콩나물", "숙주", "셀러리", "샐러리"], "agriculture.leafy"),
    # 채소/근채
    (["양파", "감자", "고구마", "당근", "무", "마늘", "생강"], "agriculture.root"),
    # 유제품
    (["우유", "치즈", "요구르트", "버터", "요거트", "크림치즈", "모짜렐라", "야쿠르트", "요플레"], "dairy"),
    # 면류
    (["라면", "국수", "파스타", "우동", "소면", "냉면", "쫄면", "칼국수", "짜파게티", "신라면"], "processed.noodle"),
    # 두부/콩
    (["두부", "콩나물", "순두부", "연두부"], "agriculture.leafy"),
    # 계란
    (["계란", "달걀", "에그", "유정란", "메추리알", "신선란"], "livestock.egg"),
    # 곡류
    (["쌀", "현미", "찹쌀", "보리", "잡곡", "오트밀"], "agriculture.grain"),
    # 수산
    (["참치", "고등어", "연어", "새우", "오징어", "멸치", "조기", "갈치", "꽃게", "전복", "굴", "홍합", "바지락", "어묵"], "seafood"),
    # 양념/소스
    (["소스", "케챱", "드레싱", "간장", "된장", "고추장", "식초", "맛술", "참기름", "들기름", "올리브유", "쌈장"], "processed.sauce"),
    # 가공식품/냉동
    (["만두", "교자", "냉동", "돈까스", "핫도그", "부대찌개", "짜장", "카레"], "processed.frozen"),
    # 과자/간식
    (["과자", "초콜릿", "사탕", "젤리", "칩", "쿠키", "크래커", "빼빼로", "포카칩"], "snack"),
    # 음료
    (["음료", "주스", "콜라", "사이다", "물", "탄산수", "이온음료", "커피", "녹차", "보리차"], "beverage"),
    # 주류
    (["맥주", "소주", "와인", "위스키", "막걸리", "하이볼", "카스", "참이슬"], "alcohol"),
    # 생활용품
    (["세제", "샴푸", "치약", "화장지", "휴지", "세탁세제", "섬유유연제", "주방세제", "물티슈", "칫솔", "메가롤"], "living"),
    # 패션
    (["티셔츠", "맨투맨", "후드", "니트", "바지", "팬츠", "자켓", "코트", "원피스", "셔츠",
      "t-shirt", "tee", "hoodie", "pants", "jacket", "coat", "dress", "shirt", "sweatshirt"], "clothing"),
]


def _fallback_categorize(product_name: str) -> Optional[str]:
    """Fuzzy Korean keyword matching — fallback when auto_categorize returns low confidence."""
    if not product_name:
        return None
    name_lower = product_name.lower()
    for keywords, cat_id in _KOREAN_KEYWORD_MAP:
        for kw in keywords:
            if kw in name_lower:
                return cat_id
    return None


def extract_weight_from_name(name: str) -> Optional[float]:
    """Extract weight in grams from product name string."""
    if not name:
        return None
    # Match patterns like "100g", "1kg", "1.5kg", "500g"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg)", name, re.IGNORECASE)
    if m:
        value = float(m.group(1))
        unit = m.group(2).lower()
        if unit == "kg":
            return value * 1000
        return value
    return None


def normalize_product_name(name: str) -> str:
    """Normalize product name for cross-mart matching.
    
    Remove store-specific prefixes, weight units, '국내산', etc.
    """
    if not name:
        return ""
    result = name

    # Remove store prefixes
    for prefix in ["이마트", "홈플러스", "롯데마트", "코스트코", "쿠팡", "SSG", "노브랜드", "피코크",
                    "심플러스", "요리하다", "L'TABLE", "초이스엘", "홈플러스시그니처"]:
        result = result.replace(prefix, "")

    # Remove origin tags
    for tag in ["국내산", "국산", "수입산", "미국산", "호주산", "스페인산", "캐나다산", "제주산", "제주직송"]:
        result = result.replace(tag, "")

    # Remove storage tags
    for tag in ["냉장", "냉동", "상온", "실온", "해동"]:
        result = result.replace(tag, "")

    # Remove weight/unit patterns
    result = re.sub(r"\d+(?:\.\d+)?\s*(?:g|kg|ml|l|리터|개|입|팩|봉|세트|매|장|병|캔|포)\b", "", result, flags=re.IGNORECASE)

    # Remove grade patterns
    result = re.sub(r"1\+\+|1\+|1등급|2등급|3등급|특등급", "", result)

    # Remove promotional text
    result = re.sub(r"\[.*?\]|\(.*?\)", "", result)

    # Remove usage suffixes
    result = re.sub(r"(구이|수육|볶음|탕|스테이크|불고기|보쌈|찜|전골|국거리|다짐)용?", "", result)

    # Clean up whitespace
    result = re.sub(r"\s+", " ", result).strip()

    return result


def group_similar_products(products: list[dict]) -> dict[str, list[dict]]:
    """Group products by normalized name + category for cross-mart comparison.
    
    Returns: {normalized_name: [product_dicts]}
    """
    groups: dict[str, list[dict]] = {}
    for p in products:
        name = p.get("name", "")
        normalized = normalize_product_name(name)
        if not normalized:
            continue
        cat = p.get("category_id", "") or ""
        # Use first-level category for grouping
        top_cat = cat.split(".")[0] if cat else ""
        key = f"{normalized}|{top_cat}" if top_cat else normalized
        groups.setdefault(key, []).append(p)
    return groups


# ──────────────────────────────────────────────
# Migration: batch auto-categorize all products
# ──────────────────────────────────────────────

def run_auto_categorize():
    """Batch auto-categorize all products in the database.
    
    Safe to re-run: only updates products that have no category_id
    or were previously auto-categorized (method = 'auto' or 'suggested').
    Also computes per_100g prices and extracts attributes.
    """
    import logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("auto_categorize_migration")

    from services.base import managed_session, get_engine
    from storage.models import Base, Product, Category, DiscountHistory, BaselinePrice

    # Ensure tables exist
    engine = get_engine()
    Base.metadata.create_all(engine)

    # First, seed categories if they don't exist
    _load_data()
    with managed_session() as session:
        existing_cats = {c.id for c in session.query(Category).all()}
        new_cats = 0
        for cat_data in (_CATEGORIES or []):
            if cat_data["id"] not in existing_cats:
                cat = Category(
                    id=cat_data["id"],
                    name=cat_data["name"],
                    parent_id=cat_data.get("parent_id"),
                    depth=cat_data.get("depth", 0),
                    sort_order=cat_data.get("sort_order", 0),
                    icon=cat_data.get("icon"),
                    attributes=cat_data.get("attributes"),
                    is_active=cat_data.get("is_active", True),
                )
                session.add(cat)
                new_cats += 1
        if new_cats:
            log.info("Seeded %d new categories", new_cats)

    # Now categorize all products
    with managed_session() as session:
        products = session.query(Product).filter(
            Product.is_active == True
        ).all()

        total = len(products)
        categorized = 0
        updated = 0
        skipped = 0

        for p in products:
            # Skip manually categorized products
            if p.category_id and p.categorization_method == "manual":
                skipped += 1
                continue

            # Run auto-categorize
            result = auto_categorize(p.name, p.source_type)
            cat_id = result.category_id
            confidence = result.confidence

            # If auto_categorize returns low confidence, try fallback
            if not cat_id or confidence < 0.3:
                fallback_cat = _fallback_categorize(p.name)
                if fallback_cat:
                    cat_id = fallback_cat
                    confidence = max(confidence, 0.4)

            if cat_id:
                # Verify category exists
                if session.get(Category, cat_id) is None:
                    # Try parent category
                    parts = cat_id.split(".")
                    while parts:
                        parent_id = ".".join(parts)
                        if session.get(Category, parent_id):
                            cat_id = parent_id
                            break
                        parts.pop()
                    else:
                        cat_id = None

            if cat_id and confidence >= 0.85:
                old_cat = p.category_id
                p.category_id = cat_id
                p.categorization_confidence = confidence
                p.categorization_method = "auto"

                # Extract and store attributes
                attrs = result.attributes if hasattr(result, 'attributes') else {}
                if attrs and not p.attributes:
                    p.attributes = attrs
                elif attrs and isinstance(p.attributes, dict):
                    merged = {**p.attributes, **attrs}
                    p.attributes = merged

                # Extract weight if not already present
                if not (p.attributes or {}).get("weight_g"):
                    weight = extract_weight_from_name(p.name)
                    if weight:
                        if p.attributes is None:
                            p.attributes = {}
                        p.attributes = {**p.attributes, "weight_g": weight}

                if old_cat != cat_id:
                    updated += 1
                categorized += 1
            else:
                if cat_id:
                    p.categorization_confidence = confidence
                    p.categorization_method = "suggested"
                skipped += 1

        log.info(
            "Auto-categorize complete: %d/%d categorized, %d updated, %d skipped",
            categorized, total, updated, skipped,
        )

    # Verify results
    with managed_session() as session:
        from sqlalchemy import func
        total = session.query(Product).count()
        cat_count = session.query(Product).filter(Product.category_id != None).count()
        log.info("Final: %d/%d products have categories", cat_count, total)

        cats = (
            session.query(Product.category_id, func.count())
            .group_by(Product.category_id)
            .all()
        )
        for cat_id, count in sorted(cats, key=lambda x: -x[1])[:15]:
            log.info("  %s: %d", cat_id, count)
