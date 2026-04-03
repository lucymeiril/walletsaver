"""WalletSavior 자동 카테고리 분류 엔진.

크롤링된 상품명을 파싱하고, 543개 카테고리 트리에서
최적의 카테고리를 매칭하여 신뢰도와 함께 반환한다.

설계 원칙:
  - 분류 실패가 **절대** 데이터 저장을 막아서는 안 된다.
  - 항상 CategorizeResult 를 반환하며, 최악의 경우 confidence=0.
  - 외부 NLP 라이브러리 없이 순수 정규식 + 사전 매칭만 사용.
"""

from __future__ import annotations

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


def _load_data():
    """카테고리/키워드/매핑 데이터를 한 번만 로드."""
    global _CATEGORIES, _KEYWORDS, _PRODUCT_MAPPINGS, _CATEGORY_MAP
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
    except ImportError:
        _CATEGORIES = []
        _KEYWORDS = []
        _PRODUCT_MAPPINGS = []
        _CATEGORY_MAP = {}


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


# ──────────────────────────────────────────────
# Step 1: Remove noise
# ──────────────────────────────────────────────

def _remove_noise(name: str) -> str:
    """Remove emojis, stars, promotional bracket tags."""
    result = _NOISE_RE.sub("", name)
    # Remove emoji unicode ranges
    result = re.sub(
        r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF"
        r"\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
        r"\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF]+",
        "", result,
    )
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
# Step 3: Split separators
# ──────────────────────────────────────────────

def _split_separators(text: str) -> list[str]:
    """Split on /, ·, |, + and whitespace. Returns non-empty tokens."""
    parts = re.split(r"[/·|+\s]+", text)
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


def _is_attribute_token(token: str) -> bool:
    """Check if a token is purely an attribute (weight, count, etc.)."""
    if re.match(r"^\d+(?:\.\d+)?\s*(?:g|kg|ml|l|리터|개|입|팩|봉|세트|T|매|장|병|캔|포)$",
                token, re.IGNORECASE):
        return True
    if re.match(r"^(?:냉장|냉동|상온|실온|해동)$", token):
        return True
    if re.match(r"^\d+(?:\.\d+)?$", token):
        return True
    return False


# ──────────────────────────────────────────────
# Step 5: Brand filtering
# ──────────────────────────────────────────────

def _identify_brand(tokens: list[str]) -> tuple[Optional[str], list[str]]:
    """Identify and remove brand from tokens. Returns (brand, remaining_tokens)."""
    brand_found: Optional[str] = None
    remaining: list[str] = []

    for token in tokens:
        token_upper = token.upper()
        matched = False
        for brand_name in KNOWN_BRANDS:
            if token == brand_name or token_upper == brand_name.upper():
                brand_found = brand_name
                matched = True
                break
        if not matched:
            remaining.append(token)

    return brand_found, remaining


# ──────────────────────────────────────────────
# Step 6: Extract pure product keywords
# ──────────────────────────────────────────────

def _extract_keywords(tokens: list[str]) -> list[str]:
    """Filter out attribute-only tokens, return pure product keywords."""
    keywords: list[str] = []
    for token in tokens:
        if not token:
            continue
        if _is_attribute_token(token):
            continue
        # remove usage suffix (e.g., "수육용" → "수육" already captured in attributes)
        cleaned = re.sub(r"용$", "", token)
        if cleaned and len(cleaned) >= 1:
            keywords.append(cleaned)
    return keywords


# ──────────────────────────────────────────────
# Full parsing pipeline
# ──────────────────────────────────────────────

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
            # Skip source tags like GS25, 이마트, etc.
            if re.match(r"^(GS25|이마트|롯데마트|홈플러스|코스트코|쿠팡|SSG)$", info):
                continue
            # Skip pure attribute bracket info (already extracted)
            if re.match(r"^(냉장|냉동|상온|실온|해동)$", info):
                continue
            if re.match(r"^(제주직송|국산|수입|수입산)$", info):
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
    """5-stage matching pipeline. Returns list of CategoryMatch candidates."""
    _load_data()
    matches: list[CategoryMatch] = []

    if not keywords:
        return matches

    # Stage 1: Exact keyword match from KEYWORDS table
    for kw in keywords:
        for entry in _KEYWORDS or []:
            if entry["word"] == kw and entry.get("category_id"):
                matches.append(CategoryMatch(
                    category_id=entry["category_id"],
                    score=0.5,
                    match_type="keyword_direct",
                    matched_token=kw,
                ))

    # Stage 2: Synonym match
    for kw in keywords:
        for entry in _KEYWORDS or []:
            if not entry.get("category_id"):
                continue
            for syn in entry.get("synonyms", []):
                if syn == kw or kw in syn or syn in kw:
                    # Exact synonym match gets full score; partial gets less
                    score = 0.4 if (syn == kw or kw == syn) else 0.3
                    matches.append(CategoryMatch(
                        category_id=entry["category_id"],
                        score=score,
                        match_type="synonym",
                        matched_token=kw,
                    ))
                    break  # one match per keyword per entry

    # Stage 3: Product mappings match
    for mapping in _PRODUCT_MAPPINGS or []:
        mapping_name = mapping["name"]
        mapping_aliases = mapping.get("aliases", [])
        mapping_cats = mapping.get("categories", [])

        if not mapping_cats:
            continue

        for kw in keywords:
            matched = False
            if kw == mapping_name or mapping_name in kw or kw in mapping_name:
                matched = True
            else:
                for alias in mapping_aliases:
                    if kw == alias or alias in kw or kw in alias:
                        matched = True
                        break

            if matched:
                for cat_id in mapping_cats:
                    matches.append(CategoryMatch(
                        category_id=cat_id,
                        score=0.45,
                        match_type="mapping",
                        matched_token=kw,
                    ))

    # Stage 4: Category name substring match
    for kw in keywords:
        if len(kw) < 2:
            continue
        for cat in _CATEGORIES or []:
            cat_name = cat["name"]
            cat_id = cat["id"]
            depth = cat.get("depth", 0)
            if kw == cat_name or (len(kw) >= 2 and kw in cat_name) or (len(cat_name) >= 2 and cat_name in kw):
                score = 0.3 + depth * 0.1
                matches.append(CategoryMatch(
                    category_id=cat_id,
                    score=score,
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
    """Aggregate scores per category_id with multi-token bonus."""
    scores: dict[str, float] = {}
    cat_tokens: dict[str, set[str]] = {}

    for c in candidates:
        # Use max score per (category, token) pair to avoid double-counting
        key = (c.category_id, c.matched_token)
        if c.category_id not in scores:
            scores[c.category_id] = 0.0
            cat_tokens[c.category_id] = set()

        # Only add score for this token if it's new for this category
        if c.matched_token not in cat_tokens[c.category_id]:
            # Take the highest score for this category-token pair
            best_score = max(
                m.score for m in candidates
                if m.category_id == c.category_id and m.matched_token == c.matched_token
            )
            scores[c.category_id] += best_score
            cat_tokens[c.category_id].add(c.matched_token)

    # Multi-token bonus: +0.15 per additional token matching same category
    for cat_id, tokens in cat_tokens.items():
        token_count = len(tokens)
        if token_count > 1:
            scores[cat_id] += 0.15 * (token_count - 1)

    return scores


# ──────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────

def auto_categorize(product_name: str, source: str | None = None) -> CategorizeResult:
    """Main auto-categorization entry point.

    NEVER raises exceptions. Always returns a CategorizeResult.
    """
    _empty_parse = ParseResult(
        original_name=product_name or "",
        cleaned_name="",
        keywords=[],
        attributes={},
        brand=None,
        bracket_info=[],
    )
    _empty_result = CategorizeResult(
        category_id=None,
        confidence=0.0,
        auto_assigned=False,
        attributes={},
        candidates=[],
        parsed_keywords=[],
        brand=None,
        parse_result=_empty_parse,
    )

    try:
        if not product_name or not product_name.strip():
            return _empty_result

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

        # Source context food bonus (on top of stage 5 already applied in match_category)
        # Already handled in match_category Stage 5

        # Phase 5: Select best
        if not scored:
            return CategorizeResult(
                category_id=None,
                confidence=0.0,
                auto_assigned=False,
                attributes=parsed.attributes,
                candidates=[],
                parsed_keywords=parsed.keywords,
                brand=parsed.brand,
                parse_result=parsed,
            )

        # Prefer deeper (more specific) categories when scores are close
        sorted_cats = sorted(scored.items(), key=lambda x: (-x[1], -_get_depth(x[0])))
        best_cat = sorted_cats[0][0]
        confidence = min(sorted_cats[0][1], 1.0)

        top_candidates = [(cat_id, min(s, 1.0)) for cat_id, s in sorted_cats[:5]]

        return CategorizeResult(
            category_id=best_cat if confidence >= 0.50 else None,
            confidence=confidence,
            auto_assigned=(confidence >= 0.85),
            attributes=parsed.attributes,
            candidates=top_candidates,
            parsed_keywords=parsed.keywords,
            brand=parsed.brand,
            parse_result=parsed,
        )

    except Exception:
        return _empty_result


def _get_depth(category_id: str) -> int:
    """Return depth of a category by its ID."""
    _load_data()
    cat = (_CATEGORY_MAP or {}).get(category_id)
    if cat:
        return cat.get("depth", 0)
    return category_id.count(".")
