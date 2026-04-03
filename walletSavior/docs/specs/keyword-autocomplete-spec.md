# 키워드 매칭 자동완성 시스템 설계 명세서

> **WalletSavior (지갑 지키미)** — 핫딜 가격 비교 사이트  
> **작성일:** 2025-07-15  
> **버전:** 1.0  
> **상태:** 설계 완료, 구현 대기

---

## 목차

1. [기획자 토론](#1-기획자-토론)
2. [최종 설계 명세](#2-최종-설계-명세)
   - 2.1 자동완성 검색 알고리즘
   - 2.2 결과 포맷
   - 2.3 랭킹/정렬 로직
   - 2.4 페이지별 변경사항
   - 2.5 인기 검색어 실시간화
   - 2.6 엣지 케이스
3. [데이터 흐름도](#3-데이터-흐름도)
4. [API 명세](#4-api-명세)
5. [구현 우선순위](#5-구현-우선순위)

---

## 1. 기획자 토론

### 참여자

| 역할 | 관점 | 핵심 가치 |
|------|------|-----------|
| **기획자 A** | 일반 사용자 (기술 무관) | 편의성 최우선 |
| **기획자 B** | 헤비유저 (가격 비교 전문가) | 정확성과 다양성 |
| **기획자 C** | UX 디자이너 | 인터랙션, 피드백, 시각적 구분 |

---

### 라운드 1: 현재 문제 진단

**기획자 A (일반 사용자):**
> 저는 장보기 전에 "돼지고기" 검색하면 삼겹살, 목심, 앞다리 등 관련 제품이 다 나올 거라 기대해요. 
> 그런데 지금은 "돼지고기"를 치면 아무것도 안 나와요. 상품명에 "돼지고기"가 들어간 게 없으니까요.
> 결국 검색을 포기하고 카테고리를 하나하나 눌러봐야 해요. 
> 검색이 안 되면 사이트 자체를 안 쓰게 됩니다.
> 
> 또 하나, 홈페이지의 "인기 검색어"가 매일 똑같아요. 
> 제가 어제도 봤고 오늘도 봤는데 순서가 안 바뀌어요. 진짜 인기 검색어가 맞나 의심이 들어요.

**기획자 B (헤비유저):**
> 저는 핫딜을 잡으려고 매일 여러 번 검색하는데, 두 가지 문제가 심각해요.
> 
> 첫째, **동의어 연결이 안 돼요.** "앞다리"를 검색하면 "앞다리살", "전지", "돼지 앞다리" 같은 
> 관련 상품이 나와야 하는데 아무것도 없어요. DB에 키워드-동의어 매핑이 있다는 걸 알고 있는데 
> 왜 안 쓰는 건지 모르겠어요.
> 
> 둘째, **상품명 부분 일치만으로는 부족해요.** 예를 들어 "계란"을 검색하면 
> "계란 30구", "계란 15구" 같은 상품은 나오지만, "달걀 30구"는 안 나와요.
> "계란"과 "달걀"이 같은 것인데 동의어 처리가 안 되니까요.
> 
> 가격 비교 사이트에서 검색 누락은 곧 돈을 잃는 거예요.

**기획자 C (UX 디자이너):**
> 현재 자동완성 드롭다운을 보면, 모든 결과가 동일한 형태로 나열돼요. 
> 검색 아이콘 + 텍스트, 그게 전부예요.
> 
> 사용자가 "삼겹살"을 쳤을 때, 이게 **키워드**(= 카테고리로 이동)인지 
> **특정 상품**(= 상품 상세로 이동)인지 구분이 안 돼요.
> 
> 또한 홈페이지 검색과 헤더 검색이 완전히 다른 로직이에요.
> 홈페이지는 클라이언트 사이드 필터링(50개 하드코딩된 상품), 
> 헤더는 API 호출. 결과가 다르게 나올 수 있어서 사용자에게 혼란을 줘요.
> 
> 검색 경험은 사이트 전체에서 **일관되어야** 합니다.

---

### 라운드 2: 해결 방향 토론

**기획자 A (일반 사용자):**
> 제가 "돼" 한 글자만 쳐도 "돼지고기", "돼지 삼겹살" 같은 게 나왔으면 좋겠어요.
> 
> 그리고 결과를 클릭했을 때 바로 "이 가격이 싼 건지 비싼 건지" 알 수 있으면 완벽해요.
> 예를 들어 "삼겹살" 키워드를 클릭하면, 삼겹살 관련 상품 목록이 가격 비교와 함께 나오는 거예요.
> 
> 한 가지 더 — **최근 검색어**가 지금도 있는데, 검색 결과가 없었던 검색어도 
> 최근 검색에 남아 있어요. 결과가 있었던 검색만 저장해주세요.

**기획자 B (헤비유저):**
> 검색 결과 우선순위가 중요해요. 제 생각에는 이런 순서가 맞아요:
> 
> 1. **키워드 정확 매칭** — "삼겹살" 입력 → "삼겹살" 키워드가 최상단
> 2. **키워드 접두어 매칭** — "삼겹" 입력 → "삼겹살" 키워드
> 3. **동의어 매칭** — "돼지고기" 입력 → 동의어에 "삼겹살"이 있는 키워드
> 4. **카테고리 이름 매칭** — "돼지" 입력 → "돼지" 카테고리의 상품들
> 5. **상품명 부분 매칭** — 위 결과에 없으면 상품명에서 직접 검색
> 
> 그리고 각 단계에서 `search_count`가 높은 것이 먼저 나와야 해요.
> 계절 식품 같은 경우 시즌에 따라 검색 빈도가 달라지니까요.
> 
> 동의어 매칭 시, 어떤 동의어가 매칭됐는지도 보여주면 좋겠어요.
> "돼지고기 → 삼겹살 (돼지고기의 한 종류)" 이런 식으로요.

**기획자 C (UX 디자이너):**
> 결과 타입별 시각적 구분이 필요해요. 제안하는 구조:
> 
> ```
> ┌─────────────────────────────┐
> │ 🔍 삼겹살                    │  ← 키워드 매칭 (볼드, 카테고리 뱃지)
> │    🏷️ 돼지고기 > 삼겹살       │     카테고리 경로
> │                              │
> │ ── 관련 상품 ─────────────── │  ← 구분선
> │ 🥩 끝돼 캐나다산 돼지 삼겹살   │  ← 상품 (아이콘, 가격 포함)
> │    100g당 ₩1,200  📉 저렴    │     가격 정보 + 가격 등급
> │ 🥩 코스트코 삼겹살 구이용      │
> │    100g당 ₩1,890  📊 보통    │
> └─────────────────────────────┘
> ```
> 
> 핵심 원칙:
> - **키워드 결과**는 상단에, 카테고리 뱃지와 함께 (클릭 시 → 카테고리 상품 목록)
> - **상품 결과**는 하단에, 가격 정보와 함께 (클릭 시 → 상품 상세)
> - 구분선으로 두 섹션을 시각적으로 분리
> - 매칭된 글자는 **하이라이트** 처리
> 
> 그리고 **빈 상태(no results)도 디자인해야 해요:**
> ```
> ┌─────────────────────────────┐
> │ 😅 "앞다리살"에 대한 결과가    │
> │    없습니다.                  │
> │                              │
> │ 이런 키워드는 어떠세요?        │
> │ 🔥 삼겹살  🔥 목심  🔥 갈비   │  ← 인기 키워드 추천
> └─────────────────────────────┘
> ```

---

### 라운드 3: 세부 사항 합의

**기획자 A (일반 사용자):**
> 한 가지 걱정이 있어요. 결과가 너무 많으면 오히려 찾기 어려워요.
> 
> "고기"를 치면 돼지고기, 소고기, 닭고기, 양고기... 키워드만 10개 넘을 수 있잖아요.
> 자동완성은 **최대 10개**가 적당한 것 같아요. 그 이상은 "전체 검색 결과 보기" 버튼으로.
> 
> 그리고 **1글자**부터 검색이 됐으면 해요. "돼" 한 글자만 쳐도 "돼지고기"가 나와야 
> 한국어 사용자에게 자연스러워요. 지금은 2글자부터인데, 한국어는 한 글자가 이미 의미를 
> 가지는 경우가 많거든요.
> 
> 모바일에서도 잘 돼야 해요. 요즘 장보기 전에 폰으로 먼저 검색하니까요.

**기획자 B (헤비유저):**
> 동의어의 **양방향 검색**이 중요해요.
> 
> - "돼지고기" 키워드의 synonyms가 `["삼겹살", "목심", "앞다리"]`일 때:
>   - "돼지고기" 검색 → "돼지고기" 키워드 출현 ✅ (정방향)
>   - "삼겹살" 검색 → "삼겹살" 키워드 출현 + "돼지고기" 키워드도 출현 ✅ (역방향)
> 
> 검색 횟수 집계도 실제 데이터여야 해요:
> - 사용자가 자동완성 결과를 클릭할 때 → 해당 키워드의 `search_count` 증가
> - 검색 후 상품을 클릭할 때도 → 해당 상품의 키워드 `search_count` 증가
> - 일별/주별 트렌드를 봐야 하니 시간대별 집계도 고려
> 
> **카테고리 계층 탐색**도 지원하면 좋겠어요:
> - "돼지" 검색 → meat.pork 카테고리 매칭 → 하위 카테고리(삼겹살, 목심, 앞다리) 키워드도 표시

**기획자 C (UX 디자이너):**
> 최종적으로 3가지 인터랙션 시나리오를 정리할게요:
> 
> **시나리오 1: 포커스만 했을 때 (빈 쿼리)**
> - 최근 검색어 (최대 5개) + 인기 검색어 (최대 8개)
> - 인기 검색어는 DB의 `search_count` 기반 실시간 데이터
> 
> **시나리오 2: 입력 중 (1글자 이상)**
> - 키워드 섹션 (최대 3개) + 상품 섹션 (최대 5개) = 최대 8개
> - 키워드에 매칭된 텍스트 하이라이트
> - 디바운스 200ms (300ms → 200ms 줄여서 반응성 향상)
> 
> **시나리오 3: 엔터 또는 "전체 결과 보기" 클릭**
> - 검색 결과 페이지로 이동 (키워드 기반 상품 목록)
> - 해당 키워드의 `search_count` 증가
> 
> **한글 입력 특이사항:**
> - 조합 중인 글자 처리 (ㄷ → 돼 → 돼지): `compositionend` 이벤트 사용
> - 자음만 입력 시 (ㄷ, ㅅ): 검색하지 않음 (완성된 글자부터)
> - 초성 검색 (ㄷㅈ → 돼지): v2에서 고려, v1에서는 제외

---

## 2. 최종 설계 명세

### 2.1 자동완성 검색 알고리즘

#### 검색 파이프라인

사용자 입력 `q`에 대해 다음 **4단계 파이프라인**을 순서대로 실행한다.

```
입력(q) → [1단계: 키워드 검색] → [2단계: 동의어 검색] → [3단계: 카테고리 이름 검색] → [4단계: 상품명 검색] → 병합/정렬 → 응답
```

##### 1단계: 키워드 직접 매칭 (Keyword Direct Match)

```sql
SELECT id, word, search_count, category_id
FROM keywords
WHERE is_active = TRUE
  AND word LIKE '{q}%'          -- 접두어 매칭
ORDER BY 
  CASE WHEN word = '{q}' THEN 0 ELSE 1 END,  -- 정확 매칭 우선
  search_count DESC
LIMIT 5;
```

- **매칭 타입:** `keyword_exact` (정확 일치) 또는 `keyword_prefix` (접두어 일치)
- **우선순위:** 정확 일치 > 접두어 일치, 그 안에서 search_count 내림차순

##### 2단계: 동의어 매칭 (Synonym Match)

```python
# synonyms JSON 배열 내에서 접두어 매칭
SELECT id, word, synonyms, search_count, category_id
FROM keywords
WHERE is_active = TRUE
  AND id NOT IN (1단계 결과 ID들)
  -- 애플리케이션 레벨에서 synonyms 필터링:
  -- any(syn.startswith(q) for syn in keyword.synonyms)
```

- **매칭 타입:** `synonym`
- **부가 정보:** `matched_synonym` 필드에 매칭된 동의어 표시
- 1단계에서 이미 나온 키워드는 중복 제거

##### 3단계: 카테고리 이름 매칭 (Category Name Match)

```sql
SELECT DISTINCT k.id, k.word, k.search_count, k.category_id
FROM keywords k
JOIN categories c ON k.category_id = c.id
WHERE k.is_active = TRUE
  AND c.is_active = TRUE
  AND c.name LIKE '%{q}%'      -- 카테고리명 포함 매칭
  AND k.id NOT IN (1~2단계 결과 ID들)
ORDER BY k.search_count DESC
LIMIT 3;
```

- **매칭 타입:** `category`
- **부가 정보:** `matched_category` 필드에 매칭된 카테고리 이름

##### 4단계: 상품명 부분 매칭 (Product Name Match)

```sql
SELECT id, name, category_id, unit, image_url
FROM products
WHERE is_active = TRUE
  AND name LIKE '%{q}%'
  AND category_id NOT IN (1~3단계에서 이미 카테고리로 커버된 ID들)
ORDER BY name
LIMIT 5;
```

- **매칭 타입:** `product`
- 1~3단계에서 이미 해당 카테고리가 키워드로 표시된 경우, 같은 카테고리의 상품은 중복 노출 방지
  (단, 검색어가 상품명에 직접 포함되는 경우는 표시)

#### 최종 병합

```python
def merge_results(keyword_results, synonym_results, category_results, product_results, limit=10):
    """
    키워드 결과 (최대 3개) + 상품 결과 (최대 5개) = 최대 8개
    여백 있으면 키워드 → 상품 순으로 채움
    """
    MAX_KEYWORDS = 3
    MAX_PRODUCTS = 5
    
    # 키워드 섹션: 1~3단계 결과 병합 (우선순위 유지)
    all_keywords = keyword_results + synonym_results + category_results
    keyword_section = all_keywords[:MAX_KEYWORDS]
    
    # 상품 섹션: 4단계 결과
    product_section = product_results[:MAX_PRODUCTS]
    
    # 키워드 슬롯에 여유가 있으면 상품으로 채움, 반대도 마찬가지
    remaining_slots = limit - len(keyword_section) - len(product_section)
    if remaining_slots > 0 and len(all_keywords) > MAX_KEYWORDS:
        keyword_section.extend(all_keywords[MAX_KEYWORDS:MAX_KEYWORDS + remaining_slots])
    
    return {
        "keywords": keyword_section,
        "products": product_section,
    }
```

---

### 2.2 결과 포맷

#### API 응답 구조

```jsonc
{
  "data": {
    "keywords": [
      {
        "type": "keyword",
        "match_type": "keyword_exact",   // keyword_exact | keyword_prefix | synonym | category
        "id": 42,
        "word": "삼겹살",
        "category_id": "meat.pork.belly",
        "category_name": "삼겹살",
        "category_path": "축산 > 돼지고기 > 삼겹살",
        "search_count": 1523,
        "matched_synonym": null,         // synonym 매칭 시에만 값 존재
        "icon": "🥩"
      },
      {
        "type": "keyword",
        "match_type": "synonym",
        "id": 15,
        "word": "돼지고기",
        "category_id": "meat.pork",
        "category_name": "돼지고기",
        "category_path": "축산 > 돼지고기",
        "search_count": 892,
        "matched_synonym": "삼겹살",     // "삼겹살" 동의어로 매칭됨
        "icon": "🐷"
      }
    ],
    "products": [
      {
        "type": "product",
        "match_type": "product_name",
        "id": 101,
        "name": "끝돼 캐나다산 돼지 삼겹살",
        "category_id": "meat.pork.belly",
        "unit": "100g",
        "icon": "🥩",
        "price_tier": "low",            // low | mid | high
        "current_price": 1200           // 현재 최저가 (선택적)
      }
    ],
    "total_keyword_count": 5,            // 전체 키워드 매칭 수 (더보기 표시용)
    "total_product_count": 23            // 전체 상품 매칭 수 (더보기 표시용)
  }
}
```

#### 프론트엔드 렌더링 구조

```
┌───────────────────────────────────────┐
│  🔍  삼겹살                            │  ← type:keyword, match_type:keyword_exact
│      축산 > 돼지고기 > 삼겹살   🥩      │     category_path + icon
│                                        │
│  🔍  돼지고기  ← "삼겹살" 포함          │  ← type:keyword, match_type:synonym
│      축산 > 돼지고기            🐷      │     matched_synonym 표시
│                                        │
│  ─── 상품 ────────────────────────── │  ← 구분선
│                                        │
│  🥩  끝돼 캐나다산 돼지 삼겹살           │  ← type:product
│      100g당 ₩1,200   📉 저렴          │     price_tier badge
│                                        │
│  🥩  코스트코 삼겹살 구이용              │
│      100g당 ₩1,890   ─ 보통           │
│                                        │
│  ──────────────────────────────────── │
│  🔍 "삼겹살" 전체 검색 결과 보기 (23건)  │  ← 전체 검색 링크
└───────────────────────────────────────┘
```

#### 빈 결과 상태

```
┌───────────────────────────────────────┐
│  😅  "앞다리살"에 대한 결과가 없습니다.  │
│                                        │
│  이런 검색어는 어떠세요?                 │
│  🔥 삼겹살   🔥 목심   🔥 갈비          │  ← 인기 키워드 3개 (fallback)
└───────────────────────────────────────┘
```

---

### 2.3 랭킹/정렬 로직

#### 우선순위 점수 체계

각 결과에 `score`를 부여하여 정렬한다:

| 매칭 유형 | 기본 점수 | 설명 |
|-----------|-----------|------|
| `keyword_exact` | **1000** | 키워드 단어가 검색어와 정확히 일치 |
| `keyword_prefix` | **800** | 키워드가 검색어로 시작 |
| `synonym` (정확) | **600** | 동의어 중 하나가 검색어와 정확히 일치 |
| `synonym` (접두어) | **500** | 동의어 중 하나가 검색어로 시작 |
| `category` | **400** | 카테고리 이름에 검색어 포함 |
| `product_name` | **200** | 상품명에 검색어 포함 |

#### 보조 정렬 기준

동일 매칭 유형 내에서:

```python
final_score = base_score + popularity_bonus

# popularity_bonus = min(search_count / 10, 100)
# 즉, search_count 1000 → 보너스 100 (최대)
```

상품의 경우 추가 기준:

```python
# 가격 정보가 있는 상품 우선
product_score = base_score
if has_price_info:
    product_score += 50
if price_tier == "low":
    product_score += 30  # 저렴한 상품 약간 우선
```

#### 정렬 예시

입력: "삼겹살"

```
1. [1000] 삼겹살 (keyword_exact, search_count: 1523)
2. [600]  돼지고기 (synonym 정확 매칭: synonyms에 "삼겹살" 포함)
3. [500]  삼겹살구이 (synonym 접두어: synonyms에 "삼겹살구이용" 포함)
   ── 상품 ──
4. [280]  끝돼 캐나다산 돼지 삼겹살 (product_name, has_price, low tier)
5. [250]  코스트코 삼겹살 구이용 (product_name, has_price, mid tier)
6. [200]  이마트 국내산 삼겹살 (product_name, has_price, high tier)
```

---

### 2.4 페이지별 변경사항

#### 2.4.1 HomePage (`packages/website/frontend/src/pages/HomePage.jsx`)

| 항목 | 현재 (AS-IS) | 변경 후 (TO-BE) |
|------|-------------|-----------------|
| 인기 검색어 | `TRENDING` 하드코딩 배열 | API `GET /api/search/trending` 호출 |
| 자동완성 소스 | `PRODUCTS.filter()` 클라이언트 사이드 | API `GET /api/search/autocomplete` 호출 |
| 검색 결과 표시 | 상품명만 텍스트 목록 | 키워드/상품 구분된 2-섹션 드롭다운 |
| 최소 입력 글자 | 1글자 (클라이언트 필터) | 1글자 (API 호출 기준) |
| 결과 없음 처리 | 드롭다운 미표시 | "결과 없음" + 인기 키워드 추천 |
| 최근 검색어 | 모든 검색 저장 | 결과가 있는 검색만 저장 |
| 검색 실행 | PRODUCTS 배열에서 찾기 | `/price/{product_id}` 또는 `/search?q={keyword}` 이동 |

**구체적 변경:**

```jsx
// AS-IS: 하드코딩
const TRENDING = ['삼겹살', '계란 30구', '양파 특가', ...];

// TO-BE: API 호출
const [trending, setTrending] = useState([]);
useEffect(() => {
  searchService.getTrending().then(res => setTrending(res.data));
}, []);
```

```jsx
// AS-IS: 클라이언트 사이드 필터링
const matches = query.length > 0
  ? PRODUCTS.filter(p => p.name.includes(query) || p.cat.includes(query))
  : [];

// TO-BE: API 호출 (Header와 동일 로직 공유)
const { suggestions, fetchAutocomplete } = useAutocomplete();
```

**공통 Hook 추출:**

```jsx
// 새 파일: hooks/useAutocomplete.js
function useAutocomplete(options = { debounce: 200, minChars: 1 }) {
  const [suggestions, setSuggestions] = useState({ keywords: [], products: [] });
  const [loading, setLoading] = useState(false);
  
  const fetch = useCallback(debounce(async (q) => {
    if (q.length < options.minChars) return setSuggestions({ keywords: [], products: [] });
    setLoading(true);
    const res = await searchService.autocomplete(q);
    setSuggestions(res.data);
    setLoading(false);
  }, options.debounce), []);
  
  return { suggestions, loading, fetch };
}
```

#### 2.4.2 Header (`packages/website/frontend/src/components/layout/Header.jsx`)

| 항목 | 현재 (AS-IS) | 변경 후 (TO-BE) |
|------|-------------|-----------------|
| 디바운스 | 300ms | 200ms |
| 최소 글자 | 2글자 | 1글자 |
| 결과 구조 | 평면 배열 `suggestions[]` | 구조화 `{ keywords: [], products: [] }` |
| 아이콘 | 모두 `Search` 아이콘 | 키워드: 🔍+카테고리, 상품: 카테고리 아이콘 |
| 클릭 동작 | 항상 동일 | 키워드→검색결과 페이지, 상품→상품상세 페이지 |
| 검색 카운트 | 미추적 | 클릭 시 `POST /api/search/track` 호출 |
| 한글 처리 | 일반 onChange | compositionEnd 이벤트 활용 |

**구체적 변경:**

```jsx
// AS-IS: 평면 목록
{suggestions.map((item, i) => (
  <button onClick={() => handleSelectSuggestion(item.text || item)}>
    <Search size={14} />
    <span>{item.text || item}</span>
  </button>
))}

// TO-BE: 섹션 분리
{suggestions.keywords?.length > 0 && (
  <div className={s.keywordSection}>
    <span className={s.sectionLabel}>키워드</span>
    {suggestions.keywords.map((kw, i) => (
      <button onClick={() => handleKeywordClick(kw)}>
        <Tag size={14} />
        <span>{highlightMatch(kw.word, query)}</span>
        <span className={s.categoryBadge}>{kw.category_path}</span>
      </button>
    ))}
  </div>
)}
{suggestions.products?.length > 0 && (
  <div className={s.productSection}>
    <span className={s.sectionLabel}>상품</span>
    {suggestions.products.map((p, i) => (
      <button onClick={() => handleProductClick(p)}>
        <span className={s.productIcon}>{p.icon}</span>
        <span>{highlightMatch(p.name, query)}</span>
        <span className={s.priceBadge}>{formatPrice(p)}</span>
      </button>
    ))}
  </div>
)}
```

**한글 조합 처리:**

```jsx
const [isComposing, setIsComposing] = useState(false);

<input
  onCompositionStart={() => setIsComposing(true)}
  onCompositionEnd={(e) => {
    setIsComposing(false);
    fetchAutocomplete(e.target.value);
  }}
  onChange={(e) => {
    setSearchQuery(e.target.value);
    if (!isComposing) {
      fetchAutocomplete(e.target.value);
    }
  }}
/>
```

#### 2.4.3 PricePage (`packages/website/frontend/src/pages/PricePage.jsx`)

| 항목 | 현재 (AS-IS) | 변경 후 (TO-BE) |
|------|-------------|-----------------|
| 검색 기능 | 없음 (상세 페이지) | 헤더 검색 공유 (변경 없음) |
| 관련 상품 | 없음 | 같은 카테고리 키워드의 관련 상품 표시 (선택적) |

PricePage는 상세 페이지이므로 자동완성 변경의 직접적 영향은 없다.
헤더의 공통 검색이 자동으로 적용된다.

**선택적 개선:** 상품 상세에서 "관련 검색어" 또는 "같은 카테고리 상품" 섹션 추가:

```jsx
// 선택적: PricePage 하단에
<RelatedKeywords categoryId={product.category_id} />
```

#### 2.4.4 신규: SearchResultsPage

키워드 클릭 시 이동할 **검색 결과 페이지** 신규 생성이 필요하다:

- **경로:** `/search?q={query}`
- **동작:** 키워드 → 카테고리 → 해당 카테고리의 모든 상품 목록 (가격 비교 포함)
- **필터:** 가격대, 용량/단위, 판매처별 필터
- 이 페이지는 별도 이슈로 관리 (본 명세 범위 밖)

---

### 2.5 인기 검색어 실시간화

#### 현재 문제

```jsx
// HomePage.jsx — 완전 하드코딩
const TRENDING = ['삼겹살', '계란 30구', '양파 특가', '코스트코', '우유 1L', '라면 5입', '휘발유', '사과'];
```

#### 해결: 실시간 인기 검색어 시스템

##### search_count 증가 시점

| 이벤트 | 증가 대상 | 증가량 |
|--------|-----------|--------|
| 자동완성에서 키워드 클릭 | 해당 키워드 | +1 |
| 자동완성에서 상품 클릭 | 해당 상품의 카테고리에 연결된 키워드 | +1 |
| 검색 결과 페이지 진입 (엔터) | 매칭된 키워드 (있으면) | +1 |

##### API 엔드포인트

**인기 검색어 조회:**

```
GET /api/search/trending?limit=8
```

```jsonc
{
  "data": [
    { "rank": 1, "word": "삼겹살", "search_count": 1523, "icon": "🥩", "change": "up" },
    { "rank": 2, "word": "계란", "search_count": 1201, "icon": "🥚", "change": "same" },
    { "rank": 3, "word": "양파", "search_count": 987, "icon": "🧅", "change": "down" },
    // ...
  ]
}
```

- `change`: 전일 대비 순위 변동 (`up` / `down` / `same` / `new`)
- 응답 캐싱: 5분 TTL (매 요청마다 DB 조회 방지)

**검색 추적:**

```
POST /api/search/track
Content-Type: application/json

{
  "keyword_id": 42,        // 키워드 클릭 시
  "product_id": 101,       // 상품 클릭 시 (선택적)
  "query": "삼겹살",       // 원본 검색어
  "source": "autocomplete" // autocomplete | trending | recent | direct
}
```

##### 백엔드 구현 (`search.py`)

```python
@router.get("/trending")
async def trending_keywords(
    request: Request,
    limit: int = Query(8, ge=1, le=20),
):
    """인기 검색어 — search_count 기준 상위 N개."""
    storage = request.app.state.storage
    keywords = storage.get_popular_keywords(limit=limit)
    return ApiResponse(data=keywords)


@router.post("/track")
async def track_search(request: Request, body: SearchTrackRequest):
    """검색 추적 — 키워드 search_count 증가."""
    storage = request.app.state.storage
    if body.keyword_id:
        storage.increment_keyword_count(body.keyword_id)
    return ApiResponse(data={"ok": True})
```

##### DBStorage 추가 메서드

```python
def get_popular_keywords(self, limit: int = 8) -> list[dict]:
    """인기 키워드 반환 (search_count 기준)."""
    with self.SessionLocal() as session:
        rows = session.execute(
            select(Keyword)
            .where(Keyword.is_active == True)
            .order_by(Keyword.search_count.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "rank": i + 1,
                "word": kw.word,
                "search_count": kw.search_count,
                "category_id": kw.category_id,
                "icon": self._get_category_icon(session, kw.category_id),
            }
            for i, kw in enumerate(rows)
        ]

def increment_keyword_count(self, keyword_id: int) -> None:
    """키워드 검색 횟수 1 증가."""
    with self.SessionLocal() as session:
        session.execute(
            update(Keyword)
            .where(Keyword.id == keyword_id)
            .values(search_count=Keyword.search_count + 1)
        )
        session.commit()
```

---

### 2.6 엣지 케이스

#### 2.6.1 한글 부분 매칭

| 입력 상태 | 예시 | 처리 방식 |
|-----------|------|-----------|
| 자음만 | ㄱ, ㅅ, ㄷ | **검색하지 않음** — 완성된 글자가 아님 |
| 한 글자 (완성) | 돼, 삼, 계 | **검색 실행** — 접두어 매칭 |
| 조합 중 | 돼ㅈ → 돼지 | `compositionend` 이벤트에서만 검색 실행 |
| 초성 검색 | ㄷㅈ → 돼지 | **v1 미지원**, v2 고려 |
| 공백 포함 | "삼겹살 구이" | 공백 기준 분리하지 않고, 전체 문자열로 매칭 |
| 영어/숫자 혼합 | "1kg 삼겹살" | 전체 문자열로 상품명 매칭 (키워드 매칭은 한글 부분만) |
| 특수문자 | "삼겹살!" | 특수문자 제거 후 검색 |

**자음 감지 로직:**

```javascript
function isIncompleteKorean(char) {
  // 한글 자음만 (ㄱ-ㅎ): U+3131 ~ U+314E
  const code = char.charCodeAt(0);
  return code >= 0x3131 && code <= 0x314E;
}

function shouldSearch(query) {
  if (!query || query.length === 0) return false;
  // 마지막 글자가 자음만이면 검색하지 않음 (조합 중일 수 있음)
  // 단, compositionend에서는 항상 검색
  const lastChar = query[query.length - 1];
  return !isIncompleteKorean(lastChar);
}
```

#### 2.6.2 결과 없음 (No Results)

**처리 흐름:**

```
4단계 모두 결과 없음
  → 인기 키워드 3개 + "결과 없음" 메시지 표시
  → 오타 교정은 v2에서 고려
```

**프론트엔드:**

```jsx
if (suggestions.keywords.length === 0 && suggestions.products.length === 0) {
  return (
    <div className={s.noResults}>
      <p>"{query}"에 대한 결과가 없습니다.</p>
      <div className={s.suggestedKeywords}>
        <span>이런 검색어는 어떠세요?</span>
        {trending.slice(0, 3).map(t => (
          <button onClick={() => handleSearch(t.word)}>{t.icon} {t.word}</button>
        ))}
      </div>
    </div>
  );
}
```

#### 2.6.3 결과 과다 (Too Many Results)

**제한 전략:**

- 키워드 섹션: 최대 **3개**
- 상품 섹션: 최대 **5개**
- 합계: 최대 **8개** (드롭다운에서 스크롤 없이 볼 수 있는 양)
- 하단에 "전체 검색 결과 보기 (N건)" 링크

**"고기" 같은 광범위 검색어:**

```
키워드: [돼지고기, 소고기, 닭고기]  ← 상위 3개 (search_count 순)
상품:   [끝돼 삼겹살, 코스트코 소고기, ...]  ← 상위 5개
전체 검색 결과 보기 (156건) →
```

#### 2.6.4 동시성 / 성능

| 우려 사항 | 대응 |
|-----------|------|
| 빠른 타이핑 시 API 과호출 | 디바운스 200ms + `AbortController`로 이전 요청 취소 |
| DB 부하 | 키워드 테이블 인덱스 활용 (이미 `ix_keywords_word` 존재) |
| 동의어 검색 성능 | 전체 키워드 로드 후 앱 레벨 필터링 (키워드 수 < 1000 가정) |
| 인기 검색어 갱신 빈도 | 5분 캐시 (서버 사이드) |
| search_count 동시 업데이트 | `UPDATE SET search_count = search_count + 1` (원자적 연산) |

#### 2.6.5 모바일 대응

- 자동완성 드롭다운 높이: 모바일에서 `max-height: 60vh`
- 키보드 올라올 때 드롭다운이 가려지지 않도록 `position: fixed` + `bottom` 배치 고려
- 터치 이벤트에서는 `onMouseEnter` 대신 `onTouchStart`로 activeIndex 처리

---

## 3. 데이터 흐름도

### 자동완성 요청 흐름

```
사용자 입력 "삼겹"
    │
    ▼
[프론트엔드]
    │  debounce 200ms
    │  compositionend 확인
    │  AbortController 이전 요청 취소
    ▼
GET /api/search/autocomplete?q=삼겹&limit=10
    │
    ▼
[백엔드: search.py autocomplete()]
    │
    ├─▶ [1단계] keywords WHERE word LIKE '삼겹%'
    │       → 삼겹살 (keyword_prefix, score: 800)
    │
    ├─▶ [2단계] keywords.synonyms 중 '삼겹' 시작하는 것
    │       → 돼지고기 (synonym=삼겹살, score: 500)
    │
    ├─▶ [3단계] categories WHERE name LIKE '%삼겹%'
    │       → (이미 1단계에서 커버됨, 스킵)
    │
    ├─▶ [4단계] products WHERE name LIKE '%삼겹%'
    │       → 끝돼 캐나다산 돼지 삼겹살 (product_name, score: 200)
    │       → 코스트코 삼겹살 구이용 (product_name, score: 200)
    │
    ▼
[병합 & 정렬]
    keywords: [삼겹살, 돼지고기]
    products: [끝돼 삼겹살, 코스트코 삼겹살]
    │
    ▼
JSON 응답 → 프론트엔드 렌더링
```

### 검색 추적 흐름

```
사용자가 "삼겹살" 키워드 클릭
    │
    ▼
[프론트엔드]
    ├─▶ POST /api/search/track  { keyword_id: 42, source: "autocomplete" }
    │       (비동기, fire-and-forget)
    │
    └─▶ navigate("/search?q=삼겹살")  또는  특정 카테고리 페이지로 이동
    
    ▼
[백엔드]
    UPDATE keywords SET search_count = search_count + 1 WHERE id = 42
```

---

## 4. API 명세

### 4.1 자동완성

```
GET /api/search/autocomplete
```

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| `q` | string | ✅ | - | 검색어 (1글자 이상) |
| `limit` | int | ❌ | 10 | 최대 결과 수 (1~50) |

**응답:** `§2.2 결과 포맷` 참조

### 4.2 인기 검색어

```
GET /api/search/trending
```

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| `limit` | int | ❌ | 8 | 최대 결과 수 (1~20) |

**응답:**

```jsonc
{
  "data": [
    { "rank": 1, "word": "삼겹살", "search_count": 1523, "icon": "🥩" }
  ]
}
```

### 4.3 검색 추적

```
POST /api/search/track
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `keyword_id` | int | ❌ | 클릭된 키워드 ID |
| `product_id` | int | ❌ | 클릭된 상품 ID |
| `query` | string | ✅ | 원본 검색어 |
| `source` | string | ✅ | `autocomplete` / `trending` / `recent` / `direct` |

**응답:** `{ "data": { "ok": true } }`

---

## 5. 구현 우선순위

### Phase 1: 백엔드 핵심 (필수, 먼저)

| # | 작업 | 대상 파일 | 설명 |
|---|------|-----------|------|
| 1 | `search_keywords()` 메서드를 website 백엔드 DBStorage에 추가 | `db.py` | 4단계 파이프라인 구현 |
| 2 | `get_popular_keywords()` 메서드 추가 | `db.py` | search_count 기반 인기 키워드 |
| 3 | `increment_keyword_count()` 메서드 추가 | `db.py` | 검색 카운트 증가 |
| 4 | `/api/search/autocomplete` 엔드포인트 개편 | `search.py` | 키워드 4단계 파이프라인 적용 |
| 5 | `/api/search/trending` 엔드포인트 신규 | `search.py` | 인기 검색어 API |
| 6 | `/api/search/track` 엔드포인트 신규 | `search.py` | 검색 추적 API |

### Phase 2: 프론트엔드 핵심 (필수, Phase 1 이후)

| # | 작업 | 대상 파일 | 설명 |
|---|------|-----------|------|
| 7 | `useAutocomplete` 공통 훅 생성 | `hooks/useAutocomplete.js` | 디바운스, compositionend, 상태 관리 |
| 8 | Header 자동완성 드롭다운 개편 | `Header.jsx` | 2-섹션 구조, 하이라이트, 아이콘 |
| 9 | HomePage 인기 검색어 API 연동 | `HomePage.jsx` | TRENDING 하드코딩 제거 |
| 10 | HomePage 자동완성 API 연동 | `HomePage.jsx` | 클라이언트 필터링 → API 호출 |
| 11 | searchService에 trending/track 추가 | `searchService.js` | API 호출 함수 |

### Phase 3: 품질 개선 (선택, Phase 2 이후)

| # | 작업 | 설명 |
|---|------|------|
| 12 | 최근 검색어 개선 | 결과 있는 검색만 저장 |
| 13 | 결과 없음 UI | 인기 키워드 추천 |
| 14 | 모바일 최적화 | 드롭다운 높이, 터치 이벤트 |
| 15 | AbortController | 이전 자동완성 요청 취소 |
| 16 | 서버 캐싱 | 인기 검색어 5분 TTL |

### Phase 4: 향후 (v2)

| # | 작업 | 설명 |
|---|------|------|
| 17 | 초성 검색 | ㄷㅈ → 돼지 |
| 18 | 오타 교정 | 편집 거리 기반 유사어 추천 |
| 19 | 검색 결과 페이지 | `/search?q=` 전용 페이지 |
| 20 | 시간대별 트렌드 | 일별/주별 인기 검색어 변동 |
| 21 | 개인화 | 사용자별 최근 검색 기반 순위 조정 |

---

> **요약:** 키워드 테이블과 동의어 매핑은 이미 DB에 존재하지만 website 백엔드에서 사용하지 않는 것이 핵심 문제다. db-admin의 `autocomplete.py` 서비스를 website 백엔드에 통합하고, 프론트엔드는 키워드/상품을 구분하는 2-섹션 드롭다운으로 개편하면 된다.
