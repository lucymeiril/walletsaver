# 동일 카테고리 상품 비교 알고리즘 기획서

## 3인 전문가 토론 기반 설계

---

## 1. 문제 정의

같은 카테고리(예: `livestock.pork.neck`)에 속하지만 이름이 다른 상품들을 공정하게 비교해야 한다.

### 핵심 난제
```
"보먹돼 목심 100G/돼지고기(목살)"  → 이마트, 100g, 냉장
"한돈 YBD 황금돼지 목심 100G/돼지고기" → 이마트, 100g, 냉장
"[냉장] 목심 수육용 500g"          → 출처 미상, 500g, 수육용
"풀무원 돼지 목살 구이용 300g"       → 풀무원, 300g, 구이용
"롯데마트 L'TABLE 목살스테이크 200g"  → 롯데, 200g, 스테이크컷
```

중량, 브랜드, 용도, 소스가 전부 다른데 "어디가 더 싼가?"를 비교해야 한다.

---

## 2. 전문가 토론

### 토론 1: 가격 정규화 — 가장 핵심

**B (데이터 과학자):** 100g vs 500g vs 1kg을 비교하려면 단위당 가격으로 정규화해야 한다. 
식품은 100g당, 음료는 100ml당이 한국 소비자에게 익숙하다.

**A (UX 디자이너):** 사용자는 "내가 사는 양 기준"으로 비교하고 싶다. 100g당은 참고용이고, 
실제 구매 단위(팩, 개)로도 보여줘야 한다.

**C (풀스택 개발자):** 정규화 로직을 백엔드에서 처리하되, 프론트에서 기준 단위를 토글할 수 있게 하자.

#### 합의사항: 이중 정규화

```python
def normalize_price(price: float, weight_g: float, count: int = 1) -> dict:
    """
    Returns:
        per_100g: 100g당 가격
        per_kg: kg당 가격
        per_unit: 1개/1팩 당 가격 (원래 판매단위 기준)
        effective_price: count 고려한 실효 가격
    """
    per_unit = price / count if count > 0 else price
    per_100g = (per_unit / weight_g * 100) if weight_g > 0 else None
    per_kg = per_100g * 10 if per_100g else None
    
    return {
        "per_100g": round(per_100g) if per_100g else None,
        "per_kg": round(per_kg) if per_kg else None,
        "per_unit": round(per_unit),
        "effective_price": round(price),
    }

# 중량 정규화 (모든 단위 → 그램)
WEIGHT_CONVERSIONS = {
    "g": 1, "kg": 1000, "근": 600, "관": 3750,
    "ml": 1, "l": 1000, "리터": 1000,  # 음료는 ml 기준
}

# 2+1 행사 처리
def handle_bundle(price, count, bonus):
    """2+1이면 count=3, 실효가격 = price / 3"""
    effective_count = count + bonus
    return price / effective_count
```

**프론트엔드 표시:**
```
목심 비교 (100g 기준)
┌─────────────────────────────────────────────┐
│ 🏷️ 보먹돼 목심        ₩1,890/100g  이마트   │ ← 녹색 (최저)
│ 🏷️ 황금돼지 목심      ₩2,100/100g  이마트   │ ← 노란색
│ 🏷️ 풀무원 목살 구이용  ₩2,450/100g  온라인   │ ← 노란색
│ 🏷️ L'TABLE 목살스테이크 ₩3,200/100g 롯데마트 │ ← 빨간색
└─────────────────────────────────────────────┘
[100g당 ▼] [개당] [kg당]  ← 단위 토글
```

---

### 토론 2: 카테고리별 비교 뷰 — 새 페이지/모드

**A:** 현재 PricePage는 개별 상품만 보여준다. 카테고리 비교 모드가 필요하다.

**C:** URL 설계: `/price/category/livestock.pork.neck` 으로 가면 해당 카테고리 전체 비교.

**B:** 상단에 요약 카드, 중간에 필터/정렬, 하단에 상품 목록. 심플하게.

#### 합의사항: 카테고리 비교 페이지 설계

**URL:** `/price/category/:categoryId`

**레이아웃:**
```
┌──────────────────────────────────────────────────┐
│ 🥩 축산물 > 돼지고기 > 목심                       │ ← 브레드크럼
├──────────────────────────────────────────────────┤
│ 📊 카테고리 요약                                  │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐│
│ │ 평균가    │ │ 최저가    │ │ 핫딜기준  │ │ 상품수 ││
│ │₩2,410/100g││₩1,890   ││₩2,000이하 ││ 12개  ││
│ │          │ │이마트     │ │          │ │       ││
│ └──────────┘ └──────────┘ └──────────┘ └───────┘│
├──────────────────────────────────────────────────┤
│ 필터: [냉장☑️][냉동☑️] [국산☑️][수입☐]            │
│ 정렬: [가격↑] [할인율↓] [최신순] [인기순]          │
│ 용도: [전체] [구이] [수육] [볶음] [스테이크]        │
├──────────────────────────────────────────────────┤
│ 📦 상품 목록 (카드 또는 테이블 뷰 토글)            │
│                                                  │
│ ┌─────────────────────────────────────────────┐  │
│ │ 🏆 Best  보먹돼 목심 100G        이마트      │  │
│ │ ₩1,890/100g  원가 ₩2,500  할인 24%         │  │
│ │ 냉장 | 국산 | 구이용  📈7일추이: ━━━━╲      │  │
│ │ [████████░░] 가격 위치 (하위 15%)           │  │
│ └─────────────────────────────────────────────┘  │
│ ┌─────────────────────────────────────────────┐  │
│ │ 한돈 YBD 황금돼지 목심 100G      이마트      │  │
│ │ ₩2,100/100g  원가 ₩2,800  할인 25%         │  │
│ │ 냉장 | 국산 | -      📈7일추이: ━━╱━━      │  │
│ │ [██████████░] 가격 위치 (하위 40%)          │  │
│ └─────────────────────────────────────────────┘  │
│                                                  │
│ 💡 "이 가격이면 앞다리살도 검토해보세요"            │
│    앞다리살 평균 ₩1,650/100g (목심보다 31% 저렴)   │
└──────────────────────────────────────────────────┘
```

**API 설계:**
```
GET /api/products/category/:categoryId/compare
  Query params:
    sort: price_asc | price_desc | discount | recent | popular
    storage: 냉장 | 냉동 | all
    origin: 국산 | 수입 | all
    usage: 구이 | 수육 | 볶음 | all
    source: emart | lotte | homeplus | online | all
    normalize: per_100g | per_kg | per_unit
    page, per_page
    
  Response:
    {
      summary: {
        avg_price_per_100g: 2410,
        min_price_per_100g: 1890,
        max_price_per_100g: 3200,
        hotdeal_threshold: 2000,  // 하위 25%
        ultra_threshold: 1700,    // 하위 10%
        product_count: 12,
        category_name: "목심",
        category_path: "축산물 > 돼지고기 > 목심",
      },
      products: [
        {
          id, name, brand, source,
          price: { current, original, discount_pct },
          normalized: { per_100g, per_kg, per_unit },
          attributes: { storage, origin, usage, weight_g, count },
          price_rank: "best" | "good" | "fair" | "expensive",
          percentile: 15,  // 하위 15%
          trend_7d: [1900, 1950, 1890, ...],
          last_updated: "2026-04-02T...",
        },
        ...
      ],
      alternatives: [
        { category_id: "livestock.pork.front_leg", name: "앞다리", avg_100g: 1650 }
      ],
      pagination: { page, per_page, total, total_pages }
    }
```

---

### 토론 3: 핫딜 기준가 정의

**B:** 카테고리별 핫딜 기준은 통계적으로 정의해야 한다. 단일 상품이 아닌 카테고리 전체의 가격 분포 기반.

**A:** 4단계 색상 시스템이 직관적이다. 초특가(파란색), 핫딜(녹색), 적정(노란색), 비쌈(빨간색).

**C:** 데이터가 적은 카테고리(2-3개)는 percentile이 의미없다. 최소 5개 이상일 때만 통계 기반, 아니면 절대 기준.

#### 합의사항: 4단계 가격 등급 시스템

```python
def compute_price_tiers(products_in_category: list) -> dict:
    """
    카테고리 내 모든 상품의 정규화 가격(per_100g)으로 등급 산정.
    
    Returns:
        ultra_threshold: 초특가 기준 (하위 10%)
        hotdeal_threshold: 핫딜 기준 (하위 25%)
        fair_threshold: 적정가 기준 (중앙값)
        expensive_threshold: 비쌈 기준 (상위 25%)
    """
    prices = sorted([p.normalized_per_100g for p in products_in_category if p.normalized_per_100g])
    
    if len(prices) < 5:
        # 데이터 부족: 최소/최대 기반 단순 분할
        min_p, max_p = prices[0], prices[-1]
        range_p = max_p - min_p
        return {
            "ultra": min_p + range_p * 0.1,
            "hotdeal": min_p + range_p * 0.25,
            "fair": min_p + range_p * 0.5,
            "expensive": min_p + range_p * 0.75,
        }
    
    # 충분한 데이터: percentile 기반
    import numpy as np
    return {
        "ultra": np.percentile(prices, 10),
        "hotdeal": np.percentile(prices, 25),
        "fair": np.percentile(prices, 50),
        "expensive": np.percentile(prices, 75),
    }

def get_price_rank(price_per_100g, tiers):
    if price_per_100g <= tiers["ultra"]:
        return {"rank": "ultra", "label": "초특가", "color": "#3B82F6", "icon": "🔥🔥"}
    elif price_per_100g <= tiers["hotdeal"]:
        return {"rank": "hotdeal", "label": "핫딜", "color": "#10B981", "icon": "🔥"}
    elif price_per_100g <= tiers["fair"]:
        return {"rank": "fair", "label": "적정가", "color": "#F59E0B", "icon": "👍"}
    else:
        return {"rank": "expensive", "label": "비쌈", "color": "#EF4444", "icon": "💸"}
```

**정부 도매가(KAMIS) 연동 (API 키 확보 후):**
```python
def adjust_with_wholesale(tiers, kamis_wholesale_price):
    """도매가 대비 소매가 마진율로 핫딜 기준 보정"""
    expected_retail = kamis_wholesale_price * 1.4  # 도매가의 1.4배가 적정 소매가
    
    # 도매가 기반 핫딜 = 도매가의 1.1~1.2배
    kamis_hotdeal = kamis_wholesale_price * 1.15
    
    # 통계 기반과 도매가 기반의 가중 평균
    tiers["hotdeal"] = tiers["hotdeal"] * 0.6 + kamis_hotdeal * 0.4
    tiers["fair"] = tiers["fair"] * 0.6 + expected_retail * 0.4
    
    return tiers
```

---

### 토론 4: 크로스소스 비교

**C:** 온라인(뽐뿌, 에펨코리아) vs 오프라인(마트) vs 도매가. 각각 성격이 다르다.

**B:** 배송비, 최소주문 등 숨겨진 비용도 고려해야 공정한 비교다.

**A:** 소스별로 태그를 붙이고, 사용자가 필터링할 수 있게 하면 된다. 총 비용(가격+배송)을 보여주되 구분은 명확히.

#### 합의사항: 소스 분류 + 총비용 표시

```python
SOURCE_TYPES = {
    "mart": {
        "sources": ["emart", "lotte", "homeplus"],
        "label": "대형마트",
        "icon": "🏬",
        "delivery_default": 0,  # 오프라인 직접 구매
        "trust_score": 0.95,
    },
    "online": {
        "sources": ["ssg", "coupang", "gmarket"],
        "label": "온라인몰",
        "icon": "🛒",
        "delivery_default": 3000,  # 기본 배송비
        "trust_score": 0.90,
    },
    "community": {
        "sources": ["ppomppu", "fmkorea", "clien"],
        "label": "커뮤니티 핫딜",
        "icon": "🗣️",
        "delivery_default": None,  # 딜마다 다름
        "trust_score": 0.70,  # 검증 안 된 정보일 수 있음
    },
    "wholesale": {
        "sources": ["kamis"],
        "label": "도매 기준가",
        "icon": "📊",
        "delivery_default": None,
        "trust_score": 1.0,
    },
}
```

**비교 화면 소스별 그룹:**
```
📊 목심 소스별 최저가 비교
┌─────────────────────────────────────┐
│ 🏬 대형마트                         │
│   이마트: ₩1,890/100g (최저)        │
│   롯데:  ₩3,200/100g               │
│   홈플:  ₩2,800/100g               │
├─────────────────────────────────────┤
│ 🛒 온라인몰                         │
│   SSG:   ₩2,100/100g +배송 ₩3,000  │
│   쿠팡:  ₩1,950/100g (로켓배송)     │
├─────────────────────────────────────┤
│ 🗣️ 커뮤니티 핫딜                    │
│   뽐뿌:  ₩1,700/100g (인증 3건)     │
├─────────────────────────────────────┤
│ 📊 도매 기준가 (KAMIS)              │
│   ₩1,200/100g (도매)               │
│   적정 소매가 ₩1,680/100g 추정      │
└─────────────────────────────────────┘
```

---

### 토론 5: 대안 추천 — "이 가격이면 차라리..."

**A:** 사용자에게 대단히 유용한 기능이다. 목심이 비싸면 앞다리로 대체할 수 있다.

**B:** 같은 대분류 내에서 다른 소분류의 평균가를 비교하면 된다.

**C:** 식당 가격과의 비교도 재미있다. "집에서 목심 500g 구이 = ₩X, 식당 목살구이 1인분 = ₩Y"

#### 합의사항: 3종 대안 추천

```python
def get_alternatives(category_id: str, current_avg: float) -> list:
    """
    1. 같은 중분류 내 저렴한 대안 (예: 목심 → 앞다리)
    2. 비슷한 가격대의 다른 카테고리 (예: 돼지 목심 가격 → 닭가슴살)
    3. 식당 가격 비교 (DB에 식당 메뉴 가격 있을 경우)
    """
    parent_id = get_parent_category(category_id)
    siblings = get_children(parent_id)
    
    # 1. 같은 부모 카테고리의 저렴한 형제
    cheaper_siblings = []
    for sib in siblings:
        if sib.id != category_id:
            avg = get_category_avg_price(sib.id)
            if avg and avg < current_avg:
                saving_pct = round((1 - avg / current_avg) * 100)
                cheaper_siblings.append({
                    "category_id": sib.id,
                    "name": sib.name,
                    "avg_per_100g": avg,
                    "saving_pct": saving_pct,
                    "suggestion": f"{sib.name}은(는) {saving_pct}% 저렴해요"
                })
    
    # 2. 비슷한 가격대 다른 카테고리
    similar_price = find_categories_in_price_range(
        current_avg * 0.8, current_avg * 1.2,
        exclude=category_id
    )
    
    # 3. 식당 비교 (해당 식재료 기반 메뉴)
    restaurant = estimate_restaurant_comparison(category_id)
    
    return {
        "cheaper_alternatives": cheaper_siblings[:3],
        "similar_price": similar_price[:3],
        "restaurant_comparison": restaurant,
    }
```

---

### 토론 6: UI 컴포넌트 트리

**A:** 기존 PricePage를 확장하자. URL에 따라 개별상품 / 카테고리비교 모드를 분기.

**C:** React Router로 중첩 라우팅:

```
/price/:productId           → ProductDetailView (기존)
/price/category/:categoryId → CategoryCompareView (신규)
/price/search               → ProductSearchView (기존 검색)
```

#### 합의사항: 컴포넌트 구조

```
PricePage.jsx (라우터 분기)
├── ProductDetailView.jsx        ← 기존 개별 상품
│   ├── PriceTimingBadge
│   ├── PriceHistoryChart (recharts AreaChart)
│   ├── MartComparisonBar
│   └── RelatedHotdeals
│
├── CategoryCompareView.jsx      ← 신규
│   ├── CategoryBreadcrumb       ← 축산물 > 돼지고기 > 목심
│   ├── CategorySummaryCards     ← 평균가, 최저가, 핫딜기준, 상품수
│   ├── CompareFilters           ← 보관, 원산지, 용도, 소스 필터
│   ├── CompareSortBar           ← 정렬 + 뷰모드(카드/테이블) 토글
│   ├── ProductCompareList       ← 정규화된 상품 카드 목록
│   │   └── ProductCompareCard   ← 개별 카드 (가격바, 스파크라인, 등급뱃지)
│   ├── SourceGroupView          ← 소스별 최저가 비교 (토글)
│   └── AlternativeSuggestions   ← 대안 추천
│
└── ProductSearchView.jsx        ← 검색 모드
```

---

## 3. DB 쿼리 패턴

```python
# 카테고리별 상품 조회 + 정규화 가격
def get_category_products(category_id, filters, sort, page, per_page):
    """
    1. products WHERE category_id = :cat (또는 하위 카테고리 포함)
    2. LEFT JOIN discount_history (최신 가격)
    3. LEFT JOIN baseline_prices (기준가)
    4. 필터 적용 (attributes JSON 쿼리)
    5. 정규화 가격 계산 (weight_g 기반)
    6. 정렬 + 페이지네이션
    """
    with session() as db:
        stmt = (
            select(Product)
            .where(Product.category_id.in_(
                get_descendant_ids(category_id)  # 하위 카테고리 포함
            ))
            .where(Product.is_active == True)
        )
        
        # 속성 필터 (SQLite JSON)
        if filters.get("storage"):
            stmt = stmt.where(
                func.json_extract(Product.attributes, '$.storage') == filters["storage"]
            )
        if filters.get("origin"):
            stmt = stmt.where(
                func.json_extract(Product.attributes, '$.origin') == filters["origin"]
            )
        
        products = db.execute(stmt).scalars().all()
        
        # 각 상품에 최신 가격 정보 결합
        results = []
        for p in products:
            latest = get_latest_price(p.id)
            weight_g = extract_weight_g(p.attributes)
            normalized = normalize_price(latest.price, weight_g) if latest else None
            results.append({**product_to_dict(p), "normalized": normalized, "latest_price": latest})
        
        # 정규화 가격 기준 정렬
        if sort == "price_asc":
            results.sort(key=lambda x: (x["normalized"] or {}).get("per_100g") or float('inf'))
        
        return paginate(results, page, per_page)
```

---

## 4. 가격 정규화 공식 요약

| 유형 | 정규화 단위 | 공식 |
|------|------------|------|
| 고기/수산/채소 | 100g당 | `price / weight_g * 100` |
| 음료/우유 | 100ml당 | `price / volume_ml * 100` |
| 계란 | 1개당 | `price / count` |
| 라면/과자 | 1봉당 | `price / count` |
| 커피/티 | 1T(스틱)당 | `price / count` |
| 밀키트 | 1인분당 | `price / servings` |
| 세제/생활용품 | 1개당 | `price / count` |

```python
NORMALIZE_RULES = {
    "agriculture": {"unit": "100g", "field": "weight_g", "multiplier": 100},
    "livestock": {"unit": "100g", "field": "weight_g", "multiplier": 100},
    "seafood": {"unit": "100g", "field": "weight_g", "multiplier": 100},
    "dairy": {"unit": "100ml", "field": "volume_ml", "multiplier": 100},
    "beverage": {"unit": "100ml", "field": "volume_ml", "multiplier": 100},
    "processed": {"unit": "개", "field": "count", "multiplier": 1},
    "snack": {"unit": "개", "field": "count", "multiplier": 1},
    "household": {"unit": "개", "field": "count", "multiplier": 1},
}

def get_normalize_unit(category_id):
    major = category_id.split('.')[0]
    return NORMALIZE_RULES.get(major, {"unit": "개", "field": "count", "multiplier": 1})
```
