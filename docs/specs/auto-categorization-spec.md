# 자동 카테고리 분류 알고리즘 기획서

## 3인 전문가 토론 기반 설계

---

## 1. 문제 정의

크롤링된 상품명은 비정형적이며 브랜드, 용도, 중량, 보관법 등 다양한 정보가 혼합되어 있다.
이를 543개 카테고리 트리(dot-notation)에 자동 분류해야 한다.

### 예시 상품명 → 목표 카테고리

| 상품명 | 목표 카테고리 ID | 난이도 |
|--------|-----------------|--------|
| `보먹돼 목심 100G/돼지고기(목살)` | `livestock.pork.neck` | 중 (브랜드 약어 + 슬래시 구분) |
| `한돈 YBD 황금돼지 삼겹살 100G/돼지고기` | `livestock.pork.belly` | 중 |
| `[냉장] 앞다리살 보쌈/수육용 1kg` | `livestock.pork.front_leg` | 중 (용도 포함) |
| `★행사★[제주직송][공육사] 제주돼지 앞다리살 500g [구이 용]` | `livestock.pork.front_leg` | 상 (노이즈 많음) |
| `드라이빗 뿌리볼륨 드라이 앞머리 미용실 웨이브컬 롤빗 특가` | `beauty.hair` | 상 (앞머리≠앞다리) |
| `[GS25] 빙그레 바나나맛우유 240ml 2개` | `dairy.milk` | 중 |
| `맥심 모카골드 커피믹스 100T 특가` | `beverage.coffee` | 하 |
| `삼겹살+목살 세트 1kg` | `livestock.pork.belly` (주) | 상 (복수 카테고리) |
| `돼지불고기 밀키트 2인분` | `processed.meal_kit` | 상 (원재료 vs 가공) |

---

## 2. 전문가 토론

### 토론 1: 상품명 파싱 파이프라인

**A (NLP 전문가):** 정규식 기반 다단계 파싱이 가장 실용적이다. 한국어 형태소 분석기(konlpy)는 상품명에는 오히려 노이즈가 많다. 상품명은 자연어가 아니라 '태그 나열'에 가깝기 때문이다.

**C (유통 전문가):** 맞다. 마트 상품명은 `[태그] 브랜드 상품명 중량/분류(부위)` 패턴이 대부분이다. 보먹돼, YBD 같은 건 이마트 PB 브랜드이고 이런 건 무시해야 한다.

**B (데이터 엔지니어):** 파싱을 단계별로 나누자. 각 단계가 독립적이면 하나가 실패해도 다음 단계에서 보완할 수 있다.

#### 합의사항: 6단계 파싱 파이프라인

```
Step 1: 노이즈 제거
  - ★, ♥, !, 이모지 제거
  - [행사], [특가], [인기], [할인], [무료배송] 등 프로모션 태그 제거
  - 정규식: /[★♥♡☆●◆▶▷◀◁♨※✔✓✗✘⚡️🔥💯🎉]+/g

Step 2: 대괄호/괄호 정보 분리 추출
  - [냉장], [냉동], [상온] → storage 속성
  - [국산], [수입], [제주], [한우] → origin 속성
  - [GS25], [이마트], [제주직송] → source/tag 속성
  - (목살), (수입산), (1등급) → 괄호 내 추가 키워드로 분리
  - 정규식: /\[([^\]]+)\]/g, /\(([^)]+)\)/g

Step 3: 슬래시/구분자 분리
  - "100G/돼지고기" → ["100G", "돼지고기"]
  - "보쌈/수육용" → ["보쌈", "수육용"]
  - 구분자: /, ·, |, _

Step 4: 구조화된 속성 추출
  - 중량: /(\d+(?:\.\d+)?)\s*(g|kg|ml|l|T|입|개|팩|봉|마리|통|세트)/i
  - 수량: /(\d+)\s*(?:개|입|팩|봉|세트|T)/
  - 용도: /(구이|수육|볶음|탕|스테이크|샤브|불고기|보쌈|찜|전골)용?/
  - 등급: /(1\+\+|1\+|1등급|2등급|3등급)/
  - 보관: /(냉장|냉동|상온|실온)/

Step 5: 브랜드 필터링
  - 알려진 PB/브랜드 사전: {보먹돼, YBD, 황금돼지, L'TABLE, 하림, 풀무원, 
    비비고, CJ, 오뚜기, 농심, 삼양, 빙그레, 매일, 서울우유, 남양, 맥심, 
    커클랜드, Kirkland, 드라이빗, 공육사...}
  - 매칭 시 브랜드 태그로 분리, 카테고리 매칭 대상에서 제외
  - 단, 브랜드가 카테고리 힌트를 포함할 수 있음 (빙그레→유제품)

Step 6: 키워드 토큰 추출
  - 위 단계에서 남은 순수 상품 키워드들
  - 예: "보먹돼 목심 100G/돼지고기(목살)" 
    → 노이즈제거 → 속성추출(100G) → 브랜드필터(보먹돼) 
    → 슬래시분리 → 키워드: ["목심", "돼지고기", "목살"]
```

---

### 토론 2: 다단계 카테고리 매칭

**A:** 추출된 키워드들을 카테고리에 매칭하는 것도 단계적으로 해야 한다. 정확할수록 높은 점수.

**B:** 기존에 keywords.py에 308개, mappings.py에 85개 매핑이 있다. 이걸 활용하면 대부분 커버된다.

**C:** 문제는 "앞머리"처럼 축산물로 오인할 수 있는 경우다. 소스 사이트 컨텍스트를 활용해야 한다. 이마트 크롤러에서 왔으면 식품일 가능성이 높고, 뽐뿌에서 왔으면 아닐 수도 있다.

#### 합의사항: 5단계 매칭 + 점수 체계

```
Stage 1: 정확 키워드 매칭 (confidence +0.5)
  - keywords 테이블에서 word == 추출토큰
  - 예: "삼겹살" == keywords.word → category_id = livestock.pork.belly
  - 여러 토큰 매칭 시 가장 구체적인 것(depth 깊은 것) 우선

Stage 2: 동의어 매칭 (confidence +0.4)
  - keywords.synonyms JSON 배열에서 토큰 검색
  - 예: "돼지고기" in keywords(word="삼겹살").synonyms → livestock.pork.belly
  - 단, 동의어는 양방향이 아닐 수 있으므로 주의

Stage 3: 매핑 테이블 매칭 (confidence +0.45)
  - mappings.py의 PRODUCT_MAPPINGS에서 name/aliases 검색
  - get_categories_for_product() 활용
  - 부분 문자열 매칭도 지원

Stage 4: 카테고리명 부분매칭 (confidence +0.3)
  - categories 테이블에서 category.name LIKE '%토큰%'
  - 예: "목심" → Category(name="목심", id="livestock.pork.neck")
  - depth가 깊을수록 보너스 (+0.1 per depth)

Stage 5: 소스 컨텍스트 기반 필터 (confidence 조정)
  - 크롤러 소스별 가중치:
    emart/lotte/homeplus → 식품 카테고리 +0.2
    뽐뿌/fmkorea/clien → 카테고리 편향 없음
  - 복수 카테고리 매칭 시 소스 컨텍스트로 결정
```

**최종 신뢰도 계산:**
```python
confidence = base_score + depth_bonus + source_bonus + multi_token_bonus

# 복수 토큰이 같은 카테고리를 가리키면 보너스
multi_token_bonus = 0.15 * (matching_tokens - 1)

# 예: "목심", "돼지고기", "목살" 모두 livestock.pork → +0.30
```

---

### 토론 3: 속성 추출 상세

**C:** 마트 상품에서 중요한 속성은: 보관법(냉장/냉동), 원산지(국산/수입), 등급(한우 1++), 중량, 용도, 수량이다.

**A:** 정규식으로 대부분 추출 가능하다. 다만 "제주돼지"에서 "제주"가 원산지인지 브랜드인지 구분이 필요하다.

**B:** attributes JSON 스키마를 표준화하자.

#### 합의사항: 표준 속성 스키마

```json
{
  "storage": "냉장|냉동|상온",
  "origin": "국산|수입|제주|미국산|호주산|스페인산",
  "grade": "1++|1+|1|2|3|특|상|보통",
  "weight_g": 100,
  "weight_unit": "g|kg|ml|l",
  "count": 1,
  "count_unit": "개|팩|봉|세트|T|입",
  "usage": "구이|수육|볶음|탕|스테이크|샤브|불고기|보쌈|찜|전골",
  "brand": "보먹돼",
  "source_tag": "GS25|이마트|제주직송",
  "normalized_price_per_100g": null
}
```

**정규식 패턴 사전:**
```python
ATTRIBUTE_PATTERNS = {
    "storage": re.compile(r'(냉장|냉동|상온|실온|해동)'),
    "origin": re.compile(r'(국산|국내산|한우|한돈|수입|수입산|미국산|호주산|스페인산|캐나다산|제주|제주산)'),
    "grade": re.compile(r'(1\+\+|1\+|1등급|2등급|3등급|특등급|특|상|보통)'),
    "weight": re.compile(r'(\d+(?:\.\d+)?)\s*(g|kg|ml|l|리터)', re.IGNORECASE),
    "count": re.compile(r'(\d+)\s*(개|입|팩|봉|세트|T|매|장|병|캔|포)', re.IGNORECASE),
    "usage": re.compile(r'(구이|수육|볶음|탕|스테이크|샤브|불고기|보쌈|찜|전골|국거리|다짐|편육|장조림)[\s]?용?'),
}
```

---

### 토론 4: 모호성 해결 (Disambiguation)

**A:** 가장 어려운 문제다. "앞머리"와 "앞다리", "치즈돈까스"와 "치즈" 등.

**C:** 핵심은 **공출현 키워드(co-occurrence)**다. "미용실"과 함께 나오면 beauty, "돼지고기"와 함께 나오면 livestock.

**B:** 매칭된 모든 카테고리 후보에 대해 다른 토큰과의 호환성을 검증하자.

#### 합의사항: 호환성 검증 알고리즘

```python
def disambiguate(token_category_pairs, source_context):
    """
    token_category_pairs: [("앞머리", ["beauty.hair", "livestock.pork.front_leg"]), ...]
    """
    # 1. 다른 토큰의 확정 카테고리에서 대분류 추출
    confirmed_majors = set()
    for token, cats in token_category_pairs:
        if len(cats) == 1:
            confirmed_majors.add(cats[0].split('.')[0])
    
    # 2. 모호한 토큰의 후보 중 확정 대분류와 같은 것 우선
    for token, cats in token_category_pairs:
        if len(cats) > 1:
            compatible = [c for c in cats if c.split('.')[0] in confirmed_majors]
            if compatible:
                cats[:] = compatible
    
    # 3. 여전히 모호하면 소스 컨텍스트 활용
    for token, cats in token_category_pairs:
        if len(cats) > 1 and source_context:
            if source_context in ('emart', 'lotte', 'homeplus'):
                food_cats = [c for c in cats if c.split('.')[0] in 
                    ('agriculture', 'livestock', 'seafood', 'processed', 'dairy', 'beverage')]
                if food_cats:
                    cats[:] = food_cats
    
    # 4. 최종: 가장 구체적인(depth 깊은) 카테고리 선택
    return select_deepest(token_category_pairs)
```

**구체적 예시:**
```
"드라이빗 뿌리볼륨 드라이 앞머리 미용실 웨이브컬 롤빗 특가"
→ 토큰: [드라이빗(브랜드), 앞머리, 미용실, 웨이브컬, 롤빗]
→ "미용실" → beauty (확정)
→ "앞머리" → beauty.hair ✓ / livestock.pork.front_leg ✗ (beauty 대분류 일치)
→ 최종: beauty.hair (confidence 0.85)

"보먹돼 목심 100G/돼지고기(목살)"
→ 토큰: [목심, 돼지고기, 목살]
→ "돼지고기" → livestock.pork (확정)
→ "목심" → livestock.pork.neck ✓ (livestock 대분류 일치)
→ "목살" → livestock.pork.neck ✓ (중복 확인)
→ 최종: livestock.pork.neck (confidence 0.95, 3토큰 일치)
```

---

### 토론 5: 신뢰도 기반 자동/수동 분기

**B:** 관리자 부담을 최소화하되 오분류를 방지해야 한다.

**A:** 3단계로 나누자. 높은 신뢰도는 자동, 중간은 제안+확인, 낮은 건 수동.

**C:** 피드백 루프도 넣어야 한다. 관리자가 수정한 매핑을 학습해서 다음에는 자동으로.

#### 합의사항: 신뢰도 임계값 + 피드백 루프

```
confidence >= 0.85 → 자동 할당 (AUTO)
  - Product.category_id 즉시 설정
  - categorization_log에 기록
  
0.50 <= confidence < 0.85 → 제안 (SUGGESTED)
  - Product.category_id = 최상위 후보 (임시)
  - PendingCategorization 레코드 생성
  - 관리자 UI에서 확인/수정
  
confidence < 0.50 → 미분류 (UNCATEGORIZED)
  - Product.category_id = NULL
  - PendingCategorization 생성 (후보 목록 포함)
  - 관리자 수동 분류

피드백 루프:
  - 관리자가 수정 시 category_corrections 테이블에 기록
  - {product_name_pattern, wrong_category, correct_category, tokens}
  - 다음 분류 시 corrections 우선 참조
  - 충분히 쌓이면 패턴 사전에 자동 추가
```

---

### 토론 6: 카테고리 ID 통일

**B:** 현재 3개 체계가 혼재. `meat.pork.belly` vs `livestock.pork.belly` vs `축산물 > 돼지고기 > 삼겹살`.

**A:** category_data/categories.py의 dot-notation(`livestock.pork.belly`)을 정본으로 하자. 543개 전체가 여기에 정의되어 있다.

**C:** seed.py의 `meat.pork.belly`는 레거시. 마이그레이션 필요.

#### 합의사항: 정규화 전략

```
정본: category_data/categories.py의 ID 체계
  - livestock.pork.belly (O)
  - meat.pork.belly (X → livestock.pork.belly로 매핑)
  - "축산물 > 돼지고기 > 삼겹살" (X → 표시용으로만 사용)

마이그레이션:
  1. LEGACY_MAP = {"meat.pork.belly": "livestock.pork.belly", ...}
  2. DB의 모든 category_id를 정규화
  3. seed.py 수정
  4. transformer.py의 한국어 경로 → dot-notation ID로 변환

카테고리 경로 생성 함수:
  def get_category_path(category_id):
      """livestock.pork.belly → '축산물 > 돼지고기 > 삼겹살'"""
      ancestors = get_ancestors(category_id)
      return " > ".join(a['name'] for a in ancestors)
```

---

### 토론 7: 엣지 케이스 처리표

| 케이스 | 예시 | 처리 방법 |
|--------|------|----------|
| 묶음상품 | "삼겹살+목살 세트 1kg" | 주 카테고리 = 첫 번째 품목 / attributes에 sub_items 배열 |
| 밀키트 | "돼지불고기 밀키트 2인분" | `processed.meal_kit` (가공식품 우선, 원재료는 attributes) |
| PB 브랜드 약어 | "보먹돼" | 브랜드 사전에서 필터링, 카테고리 매칭 제외 |
| 프로모션 태그 | "★행사★", "[특가]" | Step 1에서 제거 |
| 외국어 혼재 | "Kirkland 시그니처 삼겹살" | 브랜드 필터 후 한국어 토큰만 매칭 |
| 동음이의 | "앞머리"(미용) vs "앞다리"(축산) | 공출현 키워드 호환성 검증 |
| 복합어 | "치즈돈까스" | compound_split → [치즈, 돈까스] → processed.fried |
| 같은 제품 다른 이름 | "목심" vs "목살" | 동의어 테이블로 같은 카테고리 매핑 |
| 용도별 분류 | "삼겹살 구이용" vs "삼겹살 수육용" | 같은 카테고리, usage 속성으로 구분 |
| 중량 단위 혼재 | "100G", "1kg", "500ML" | 정규화: 모두 g 또는 ml 단위로 변환 |

---

## 3. 최종 통합 알고리즘 명세

### 전체 파이프라인 의사코드

```python
def auto_categorize(product_name: str, source: str = None) -> CategorizeResult:
    """
    Args:
        product_name: 크롤링된 원본 상품명
        source: 크롤러 소스 (emart, homeplus, ppomppu 등)
    
    Returns:
        CategorizeResult(category_id, confidence, attributes, candidates)
    """
    
    # Phase 1: 파싱
    cleaned = remove_noise(product_name)
    bracket_info = extract_brackets(cleaned)        # [냉장], (목살) 등
    slash_tokens = split_separators(cleaned)         # / · | 분리
    attributes = extract_attributes(bracket_info + slash_tokens)  # 중량, 보관, 용도
    brand = identify_brand(slash_tokens)             # 브랜드 식별 및 제거
    keywords = extract_keywords(slash_tokens, brand) # 순수 상품 키워드
    
    # Phase 2: 매칭
    candidates = []
    
    # Stage 1: 정확 키워드 매칭
    for kw in keywords:
        matches = keyword_exact_match(kw)  # keywords 테이블
        candidates.extend([(m, 0.50) for m in matches])
    
    # Stage 2: 동의어 매칭
    for kw in keywords:
        matches = synonym_match(kw)        # synonyms JSON 배열
        candidates.extend([(m, 0.40) for m in matches])
    
    # Stage 3: 매핑 테이블 매칭
    full_name = " ".join(keywords)
    matches = mapping_match(full_name)     # PRODUCT_MAPPINGS
    candidates.extend([(m, 0.45) for m in matches])
    
    # Stage 4: 카테고리명 부분매칭
    for kw in keywords:
        matches = category_name_match(kw)  # category.name LIKE
        candidates.extend([(m, 0.30 + m.depth * 0.1) for m in matches])
    
    # Phase 3: 모호성 해결
    if len(set(c[0] for c in candidates)) > 1:
        candidates = disambiguate(candidates, keywords, source)
    
    # Phase 4: 점수 집계
    scored = aggregate_scores(candidates)
    # 같은 카테고리 복수 매칭 보너스
    for cat_id, score in scored.items():
        token_count = count_matching_tokens(cat_id, keywords)
        scored[cat_id] += 0.15 * (token_count - 1)
    
    # 소스 컨텍스트 보너스
    if source in ('emart', 'lotte', 'homeplus'):
        for cat_id in scored:
            if cat_id.split('.')[0] in FOOD_CATEGORIES:
                scored[cat_id] += 0.1
    
    # Phase 5: 결과 결정
    best_cat = max(scored, key=scored.get) if scored else None
    confidence = scored.get(best_cat, 0) if best_cat else 0
    confidence = min(confidence, 1.0)
    
    # 피드백 보정 적용
    correction = check_corrections(product_name, best_cat)
    if correction:
        best_cat = correction.correct_category
        confidence = max(confidence, 0.90)  # 보정된 건 높은 신뢰도
    
    return CategorizeResult(
        category_id=best_cat if confidence >= 0.50 else None,
        confidence=confidence,
        auto_assigned=(confidence >= 0.85),
        attributes=attributes,
        candidates=sorted(scored.items(), key=lambda x: -x[1])[:5],
        parsed_keywords=keywords,
        brand=brand,
    )

FOOD_CATEGORIES = {'agriculture', 'livestock', 'seafood', 'processed', 'dairy', 'beverage'}
```

### 필요 데이터 구조

```python
# 새 테이블: 미분류 큐
class PendingCategorization(Base):
    id: int
    product_id: int (FK → products)
    suggested_category_id: str?
    confidence: float
    candidates_json: list  # 상위 5개 후보 [{category_id, score}]
    parsed_keywords: list
    parsed_attributes: dict
    status: str  # "pending" | "approved" | "corrected" | "skipped"
    admin_category_id: str?  # 관리자가 지정한 최종 카테고리
    created_at: datetime

# 새 테이블: 보정 이력
class CategoryCorrection(Base):
    id: int
    product_name_pattern: str  # 매칭에 사용할 패턴
    wrong_category_id: str
    correct_category_id: str
    tokens: list  # JSON
    created_at: datetime

# 기존 테이블 수정: Product
class Product(Base):
    # 추가 필드
    categorization_confidence: float?
    categorization_method: str?  # "auto" | "suggested" | "manual" | "corrected"
```

### 기존 코드 연동 포인트

```
1. pipeline/transformer.py → enrich_with_category() 교체
   - 17개 하드코딩 → auto_categorize() 함수 호출
   
2. api/routes/ingestion.py → _ensure_product() 수정
   - Product 생성 시 auto_categorize() 호출
   - confidence >= 0.85: category_id 자동 설정
   - confidence < 0.85: PendingCategorization 레코드 생성
   
3. db-admin 프론트엔드 → 미분류 큐 관리 UI
   - 상품 탭에 "미분류 상품" 서브탭
   - 후보 카테고리 드롭다운, 확인/수정 버튼
   - 보정 이력 조회
   
4. category_data/keywords.py → auto_categorize의 Stage 1,2 데이터
5. category_data/mappings.py → auto_categorize의 Stage 3 데이터
6. category_data/categories.py → Stage 4 데이터 + 카테고리 트리
```

---

## 4. 브랜드 사전 (초기)

```python
KNOWN_BRANDS = {
    # 이마트 PB
    "보먹돼", "YBD", "황금돼지", "피코크", "노브랜드", "일품포크",
    # 롯데마트 PB
    "L'TABLE", "초이스엘", "요리하다",
    # 홈플러스 PB
    "심플러스", "홈플러스시그니처",
    # 식품 브랜드
    "하림", "풀무원", "비비고", "CJ", "오뚜기", "농심", "삼양",
    "빙그레", "매일", "서울우유", "남양", "파스퇴르", "맥심",
    "동원", "사조", "진주햄", "롯데햄", "대상", "청정원",
    # 해외 브랜드
    "Kirkland", "커클랜드", "코스트코",
    # 비식품
    "드라이빗", "공육사", "무인양품",
}

# 브랜드이면서 카테고리 힌트인 경우
BRAND_CATEGORY_HINTS = {
    "빙그레": "dairy",
    "서울우유": "dairy",
    "하림": "livestock.chicken",
    "동원": "seafood",
}
```
