# 🎯 Product Modal & Search UX 개선 명세서

> **문서 버전:** v1.0  
> **작성일:** 2025-07-23  
> **목적:** ProductQuickView 모달의 정보 보강 + SearchPage 자동완성 기능 통합  
> **관련 사용자 피드백:** _"마트 할인 쪽 모달처럼 다 보여줘야 하고"_, _"검색 화면의 상단 검색바는 키워드 매칭이나 자동완성이 하나도 안돼"_

---

## 목차

1. [현상 분석 및 문제 정의](#1-현상-분석-및-문제-정의)
2. [ProductQuickView 리디자인](#2-productquickview-리디자인)
3. [SearchPage 자동완성 통합](#3-searchpage-자동완성-통합)
4. [공통 Autocomplete 컴포넌트 설계](#4-공통-autocomplete-컴포넌트-설계)
5. [API 변경 사항](#5-api-변경-사항)
6. [구현 단계 및 파일 변경 목록](#6-구현-단계-및-파일-변경-목록)
7. [접근성 및 모바일 고려사항](#7-접근성-및-모바일-고려사항)

---

## 1. 현상 분석 및 문제 정의

### 1.1 ProductQuickView — "쓸모없는 껍데기" 문제

**현재 표시 정보 (ProductQuickView.jsx, 79줄):**

| 항목 | 표시 여부 | 비고 |
|------|-----------|------|
| 상품명 | ✅ | Modal title로 표시 |
| 현재가 | ✅ | `{price}원 / {unit}` |
| 소스 타입 | ✅ | 대부분 "unknown"으로 표시 → 무의미 |
| 카테고리 경로 | ✅ | 중복 표시됨 (칩 + 행) |
| 상품 이미지 | ❌ | 없음 |
| 정가(원가) | ❌ | 없음 |
| 할인율 | ❌ | 없음 |
| 할인 기간 | ❌ | 없음 |
| 규격/단위 상세 | ❌ | unit만 가격 옆에 작게 |
| 장보기 추가 | ❌ | 없음 |
| 외부 링크 | ❌ | 없음 |

**MartProductModal과의 격차:**

```
MartProductModal (145줄)          ProductQuickView (79줄)
─────────────────────────          ────────────────────────
🖼️  상품 이미지 + 할인 뱃지       ❌ 이미지 없음
💰 판매가 (강조)                  💰 가격 (기본)
💸 정가 (취소선)                  ❌ 없음
📉 할인율 (-XX%)                  ❌ 없음
🏷️  행사 유형                     ❌ 없음
📏 규격/단위                     ❌ 없음 (unit만 작게)
🏪 판매 매장                     ❌ 없음
🛒 마트명                        ❌ 없음
📅 행사 기간                     ❌ 없음
🔗 상품 페이지 이동               ❌ 없음
🛒 온라인몰 검색                  ❌ 없음
📊 카테고리 비교                  ✅ 있음
🛒 장보기 추가                    ❌ 없음
```

**사용자 심리:** 자동완성에서 상품을 클릭했는데 이름과 가격만 덩그러니 → _"이게 뭐야?"_ → 즉시 닫기 → 서비스 이탈

### 1.2 SearchPage — "반쪽짜리 검색" 문제

**현재 SearchPage 검색바 (SearchPage.jsx, 123-132줄):**

```jsx
// 현재: 단순 form + input. 자동완성 없음.
<form className={s.searchForm} onSubmit={handleSubmit}>
  <Search size={20} className={s.formIcon} />
  <input
    type="search"
    value={inputValue}
    onChange={(e) => setInputValue(e.target.value)}
    placeholder="상품, 핫딜, 커뮤니티 검색..."
  />
</form>
```

**Header 검색바와의 기능 비교:**

| 기능 | Header 검색바 | SearchPage 검색바 |
|------|--------------|------------------|
| 자동완성 API 호출 | ✅ 200ms debounce | ❌ 없음 |
| 키워드 섹션 (🔍) | ✅ 카테고리 경로 + 동의어 힌트 | ❌ 없음 |
| 상품 섹션 (📦) | ✅ 아이콘 + 이름 + 단위 + 가격 | ❌ 없음 |
| 키보드 내비게이션 | ✅ ↑↓ Enter Escape | ❌ Enter만 (form submit) |
| 최근 검색어 | ✅ 검색어 없을 때 표시 | ❌ 없음 |
| 인기 검색어 | ✅ 🔥 트렌딩 키워드 | ❌ 없음 |
| 검색 추적 | ✅ trackKeyword() 호출 | ❌ 없음 |
| 매칭 하이라이트 | ✅ `<strong>` 태그 | ❌ 없음 |

**사용자 시나리오 (불편):**
1. Header에서 "삼겹살" 검색 → 자동완성 드롭다운에서 "📦 삼겹살 600g · 12,900원" 보임 → 편리
2. SearchPage로 이동됨 → 다시 검색하고 싶은데 → SearchPage의 검색바에 "돼지고기" 입력
3. 자동완성이 전혀 안 됨 → _"아까는 됐는데 왜 안 돼?"_ → 혼란

### 1.3 핵심 원칙

이 개선의 핵심은 **일관성(Consistency)**:
- 어디서 검색하든 **같은 자동완성 경험**
- 어디서 상품을 클릭하든 **같은 수준의 정보 표시**
- 사용자가 _"이건 쓸만하다"_ 라고 느끼는 **최소 정보 임계값**을 넘기는 것

---

## 2. ProductQuickView 리디자인

### 2.1 데이터 소스 분석

현재 `openProductModal(p)`로 전달되는 데이터는 자동완성 API 응답의 product 객체:

```json
{
  "type": "product",
  "id": 42,
  "name": "삼겹살 (국산, 냉장)",
  "unit": "100g",
  "icon": "🥩",
  "current_price": 2980,
  "original_price": 3500,
  "discount_pct": 15,
  "source_type": "mart_crawl",
  "has_baseline": true,
  "suggested_action": "product_modal"
}
```

**부족한 데이터:**
- `image_url` — 없음 → **API 보강 필요**
- `description` — 없음 → **API 보강 필요**
- `category_id`, `category_path` — 없음 → **API 보강 필요**
- `valid_from`, `valid_to` (할인 기간) — 없음 → **API 보강 필요**
- `source_url` (상품 상세 링크) — 없음 → **API 보강 필요**
- `source` (출처명: 이마트/홈플러스 등) — 없음 → **API 보강 필요**

**해결 전략: 2단계 로딩 (즉시 표시 + 비동기 보강)**

```
┌─────────────────────────────────────────┐
│  Phase 1: 즉시 표시 (props 데이터)       │
│  - 상품명, 현재가, 단위, 할인율          │
│  - 스켈레톤 이미지 placeholder           │
│                                         │
│  Phase 2: API fetch (GET /api/products/:id)│
│  - image_url → 이미지 로드              │
│  - description → 상품 설명 표시          │
│  - category_path → 카테고리 칩           │
│  - 할인 기간, 출처명, 상세 링크          │
│  - 매장별 가격 비교 데이터               │
└─────────────────────────────────────────┘
```

### 2.2 새로운 UI 레이아웃

```
┌─────────────────────────────────────────────────┐
│  ✕  삼겹살 (국산, 냉장)                    [닫기]│  ← Modal title
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌─────────────────────────────────────────┐   │
│  │                                         │   │
│  │           🖼️  상품 이미지                │   │  ← 200×200, object-fit: contain
│  │           (로딩 중: 스켈레톤)            │   │
│  │                                    -15% │   │  ← 할인 뱃지 (discBadge)
│  │                                         │   │
│  └─────────────────────────────────────────┘   │
│                                                 │
│  📁 축산 > 돼지고기 > 삼겹살                     │  ← 카테고리 칩 (categoryChip)
│                                                 │
│  ─────────────────────────────────────────────  │
│  판매가            2,980원                      │  ← sale (강조, accent color)
│  ─────────────────────────────────────────────  │
│  정가              3,500원                      │  ← orig (취소선)
│  ─────────────────────────────────────────────  │
│  할인율            -15%                         │  ← disc (빨간색)
│  ─────────────────────────────────────────────  │
│  규격/단위         100g                         │
│  ─────────────────────────────────────────────  │
│  출처              이마트                        │  ← source (Phase 2)
│  ─────────────────────────────────────────────  │
│  할인 기간         2025.01.15 ~ 2025.01.22      │  ← valid_from ~ valid_to (Phase 2)
│  ─────────────────────────────────────────────  │
│                                                 │
│  ┌─────────────────────────────────────────┐   │
│  │  🔗 상품 페이지로 이동                    │   │  ← linkBtn (Phase 2, source_url)
│  └─────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────┐   │
│  │  🛒 SSG.COM에서 검색                     │   │  ← mallBtn (조건부, source에 따라)
│  └─────────────────────────────────────────┘   │
│  ┌────────────────────┐┌────────────────────┐  │
│  │ 📊 물가비교 상세    ││ 📁 카테고리 비교    │  │  ← 기존 버튼 유지
│  └────────────────────┘└────────────────────┘  │
│  ┌────────────────────┐┌────────────────────┐  │
│  │ 🛒 장보기에 추가    ││     닫기            │  │  ← 장보기 추가 (신규)
│  └────────────────────┘└────────────────────┘  │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 2.3 컴포넌트 구조 (새 ProductQuickView.jsx)

```jsx
// packages/website/frontend/src/components/modals/ProductQuickView.jsx

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';
import Modal from '../common/Modal';
import useStore from '../../stores/appStore';
import { productService } from '../../services/productService';
import { fmt } from '../../utils/helpers';
import s from './ProductQuickView.module.css';

const MART_ONLINE_URLS = {
  emart:    { name: 'SSG.COM',     searchUrl: 'https://www.ssg.com/search.ssg?query=' },
  homeplus: { name: '홈플러스몰',   searchUrl: 'https://mfront.homeplus.co.kr/search?keyword=' },
  lotte:    { name: '롯데온',       searchUrl: 'https://www.lottemart.com/search/search/search.do?keyword=' },
  costco:   { name: '코스트코',     searchUrl: 'https://www.costco.co.kr/search?text=' },
};

export default function ProductQuickView({ data, onClose }) {
  const navigate = useNavigate();
  const addToShoppingList = useStore((st) => st.addToShoppingList);
  const addToast = useStore((st) => st.addToast);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  // Phase 1: 즉시 사용 가능한 데이터 (props)
  const name        = data?.name || data?.product_name || '상품';
  const price       = data?.current_price ?? data?.price ?? null;
  const origPrice   = data?.original_price ?? null;
  const discountPct = data?.discount_pct ?? data?.discount ?? null;
  const unit        = data?.unit ?? '';
  const icon        = data?.icon ?? '📦';
  const categoryId  = data?.category_id ?? null;
  const productId   = data?.id ?? null;
  const sourceType  = data?.source_type ?? '';

  // Phase 2: API에서 보강된 데이터
  useEffect(() => {
    if (!productId) return;
    setLoading(true);
    productService.getDetail(productId)
      .then(res => setDetail(res.data || res))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [productId]);

  // Phase 2 데이터 머지 (API 응답이 더 풍부)
  const image       = detail?.img || detail?.image_url || data?.image_url || '';
  const categoryPath= detail?.category_path || data?.category_path || '';
  const description = detail?.description || '';
  const sourceUrl   = detail?.source_url || data?.source_url || '';
  const source      = detail?.source || data?.source || '';
  const validFrom   = detail?.valid_from || '';
  const validTo     = detail?.valid_to || '';

  // 판매가/정가 — detail이 더 정확할 수 있음
  const salePrice = detail?.cur ?? price;
  const origFinal = detail?.original_price ?? origPrice;
  const discFinal = discountPct ?? (
    salePrice && origFinal && origFinal > 0
      ? Math.round((1 - salePrice / origFinal) * 100)
      : null
  );

  // 온라인몰 URL
  const martKey = source?.toLowerCase() || sourceType?.replace('_crawl', '') || null;
  const mallInfo = martKey ? MART_ONLINE_URLS[martKey] : null;
  const onlineUrl = mallInfo && name
    ? `${mallInfo.searchUrl}${encodeURIComponent(name)}`
    : null;

  // 핸들러
  const handlePriceCompare    = () => { onClose(); if (productId) navigate(`/price/${productId}`); };
  const handleCategoryCompare = () => { if (categoryId) { onClose(); navigate(`/price/category/${categoryId}`); } };
  const handleAddToCart        = () => {
    addToShoppingList({ name, price: salePrice, icon });
    addToast(`${name}을(를) 장보기 리스트에 추가했어요`, 'success');
    onClose();
  };

  if (!data) return null;

  return (
    <Modal isOpen onClose={onClose} title={name} size="sm">
      <div className={s.body}>
        {/* 이미지 섹션 */}
        <div className={s.imgWrap}>
          {image ? (
            <img src={image} alt={name} className={s.img} />
          ) : (
            <div className={s.imgPlaceholder}>
              <span className={s.imgEmoji}>{icon}</span>
            </div>
          )}
          {discFinal > 0 && (
            <span className={s.discBadge}>-{discFinal}%</span>
          )}
        </div>

        {/* 카테고리 칩 */}
        {categoryPath && (
          <span className={s.category}>📁 {categoryPath}</span>
        )}

        {/* 가격 정보 행 */}
        {salePrice != null && (
          <div className={s.row}>
            <span className={s.label}>판매가</span>
            <span className={s.sale}>{fmt(salePrice)}원</span>
          </div>
        )}
        {origFinal > 0 && origFinal !== salePrice && (
          <div className={s.row}>
            <span className={s.label}>정가</span>
            <span className={s.orig}>{fmt(origFinal)}원</span>
          </div>
        )}
        {discFinal > 0 && (
          <div className={s.row}>
            <span className={s.label}>할인율</span>
            <span className={s.disc}>-{discFinal}%</span>
          </div>
        )}
        {unit && (
          <div className={s.row}>
            <span className={s.label}>규격/단위</span>
            <span>{unit}</span>
          </div>
        )}
        {source && (
          <div className={s.row}>
            <span className={s.label}>출처</span>
            <span>{source}</span>
          </div>
        )}
        {(validFrom || validTo) && (
          <div className={s.row}>
            <span className={s.label}>할인 기간</span>
            <span>{validFrom} ~ {validTo}</span>
          </div>
        )}

        {/* 로딩 인디케이터 */}
        {loading && (
          <div className={s.loadingRow}>상세 정보 불러오는 중...</div>
        )}

        {/* 액션 버튼 */}
        <div className={s.actions}>
          {sourceUrl && (
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className={s.linkBtn}>
              <ExternalLink size={16} /> 상품 페이지로 이동
            </a>
          )}
          {onlineUrl && mallInfo && (
            <a href={onlineUrl} target="_blank" rel="noopener noreferrer" className={s.mallBtn}>
              🛒 {mallInfo.name}에서 검색
            </a>
          )}
          {productId && (
            <button className={s.compareBtn} onClick={handlePriceCompare}>
              📊 물가비교 상세 보기
            </button>
          )}
          {categoryId && (
            <button className={s.categoryBtn} onClick={handleCategoryCompare}>
              📁 카테고리 비교
            </button>
          )}
          <button className={s.cartBtn} onClick={handleAddToCart}>
            🛒 장보기에 추가
          </button>
          <button className={s.closeBtn} onClick={onClose}>닫기</button>
        </div>
      </div>
    </Modal>
  );
}
```

### 2.4 새 CSS 레이아웃 (ProductQuickView.module.css)

기존 `.body`, `.row`, `.label`, `.actions`, `.compareBtn`, `.closeBtn`은 유지하면서,
MartProductModal.module.css에서 검증된 스타일을 차용한다:

**추가할 CSS 클래스:**

```css
/* ── 이미지 영역 ── */
.imgWrap {
  position: relative;
  display: flex;
  justify-content: center;
  padding: var(--space-md);
  background: var(--glass);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}
.img {
  width: 200px;
  height: 200px;
  object-fit: contain;
  border-radius: var(--radius);
}
.imgPlaceholder {
  width: 200px;
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--glass2);
  border-radius: var(--radius);
}
.imgEmoji {
  font-size: 3rem;
}
.discBadge {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: var(--fw-bold);
  color: #fff;
  background: var(--red);
}

/* ── 가격 스타일 ── */
.sale {
  font-size: var(--fs-lg);
  font-weight: var(--fw-bold);
  color: var(--accent);
}
.orig {
  text-decoration: line-through;
  color: var(--text3);
}
.disc {
  font-weight: var(--fw-bold);
  color: var(--red);
}

/* ── 로딩 ── */
.loadingRow {
  text-align: center;
  padding: 8px;
  font-size: var(--fs-xs);
  color: var(--text3);
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ── 버튼 추가 ── */
.linkBtn { /* MartProductModal의 .linkBtn과 동일 */ }
.mallBtn { /* MartProductModal의 .mallBtn과 동일 */ }
.categoryBtn { /* MartProductModal의 .categoryBtn과 동일 */ }
.cartBtn { /* MartProductModal의 .cartBtn과 동일 */ }
```

### 2.5 사용자 인터랙션 흐름

```
사용자: Header에서 "삼겹살" 타이핑
       ↓
자동완성: 📦 삼겹살 (국산, 냉장) / 100g · 2,980원  ← 클릭
       ↓
suggested_action === "product_modal"
       ↓
modalStore.openProductModal(p)  ← 자동완성 데이터 전달
       ↓
ProductQuickView 렌더링 (Phase 1)
  ┌───────────────────────────────┐
  │  🥩 (아이콘 placeholder)      │  ← 이미지 아직 로딩 중
  │  판매가: 2,980원              │  ← props 데이터 즉시 표시
  │  정가:   3,500원              │
  │  할인율: -15%                 │
  │  규격:   100g                 │
  │  [상세 정보 불러오는 중...]     │  ← 로딩 텍스트
  └───────────────────────────────┘
       ↓
GET /api/products/42  ← 비동기 API 호출 (~200ms)
       ↓
Phase 2 데이터 도착
  ┌───────────────────────────────┐
  │  🖼️ [실제 상품 이미지]   -15% │  ← 이미지 로드 완료
  │  📁 축산 > 돼지고기 > 삼겹살   │  ← 카테고리 경로
  │  판매가: 2,980원              │
  │  정가:   3,500원              │
  │  할인율: -15%                 │
  │  규격:   100g                 │
  │  출처:   이마트                │  ← 새로 표시
  │  기간:   01.15 ~ 01.22        │  ← 새로 표시
  │  ──────────────────────────── │
  │  [🔗 상품 페이지로 이동]       │
  │  [🛒 SSG.COM에서 검색]        │
  │  [📊 물가비교] [📁 카테고리]   │
  │  [🛒 장보기 추가] [닫기]       │
  └───────────────────────────────┘
```

**포인트:** Phase 1에서 즉시 의미 있는 정보(가격, 할인율)를 보여주므로 사용자는 체감 로딩 시간이 거의 없다. Phase 2는 보강 데이터(이미지, 출처, 기간)를 자연스럽게 채워넣는다.

---

## 3. SearchPage 자동완성 통합

### 3.1 현재 문제의 원인

Header.jsx는 **자동완성 로직을 인라인으로 구현**(84-106줄: debounce, 129-135줄: input handler, 193-223줄: keyboard navigation, 313-419줄: dropdown rendering). 이 로직이 Header 내부에 하드코딩되어 있어 SearchPage에서 재사용할 수 없다.

### 3.2 해결 전략: 공통 컴포넌트 추출

```
AS-IS (현재)                        TO-BE (개선 후)
─────────────                       ───────────────

Header.jsx                          Header.jsx
├── searchQuery state               ├── <SearchAutocomplete
├── keywords/products state             variant="header"
├── debounce logic                       placeholder="상품, 가격, 핫딜 검색..."
├── fetchAutocomplete()                  onSearch={handleSearch}
├── handleKeyDown()                      onKeywordClick={handleKeywordClick}
├── handleKeywordClick()                 onProductClick={handleProductClick}
├── handleProductClick()             />
├── <input> + <dropdown>
└── (모든 로직 인라인)                SearchPage.jsx
                                    ├── <SearchAutocomplete
SearchPage.jsx                          variant="page"
├── <input> (자동완성 없음)               placeholder="상품, 핫딜, 커뮤니티 검색..."
└── form submit만                        onSearch={handleSubmit}
                                         onKeywordClick={handleKeywordClick}
                                         onProductClick={handleProductClick}
                                         autoFocus
                                    />

                                    SearchAutocomplete.jsx (새 공통 컴포넌트)
                                    ├── searchQuery state
                                    ├── keywords/products state
                                    ├── trendingKeywords state
                                    ├── recentSearches (store)
                                    ├── debounce logic (200ms)
                                    ├── fetchAutocomplete()
                                    ├── handleKeyDown() (↑↓ Enter Escape)
                                    ├── highlightMatch()
                                    ├── <input> + <dropdown>
                                    └── 모든 자동완성 UI/로직 캡슐화
```

### 3.3 SearchPage 개선 후 UI 레이아웃

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ 🔍  삼겹ㄱ                                    [✕]  │  │  ← SearchAutocomplete
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  키워드                                            │  │
│  │  🔍 삼겹살         축산 > 돼지고기 > 삼겹살         │  │  ← 키워드 섹션
│  │  🔍 삼겹살구이     축산 > 돼지고기 > 삼겹살         │  │
│  │  ────────────────────────────────────────────────  │  │
│  │  상품                                              │  │
│  │  🥩 삼겹살 (국산, 냉장)     100g · 2,980원         │  │  ← 상품 섹션
│  │  🥩 삼겹살 (수입, 냉동)     100g · 1,890원         │  │
│  │  🥩 대패삼겹살              200g · 5,900원         │  │
│  │  ────────────────────────────────────────────────  │  │
│  │  🔍 "삼겹ㄱ" 전체 검색 결과 보기 (12건)             │  │  ← 전체 검색 footer
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ────────────────────────────────────────────────────    │
│  '삼겹살' 검색 결과                     [관련순 ▾]       │
│  ────────────────────────────────────────────────────    │
│  전체(8) | 상품(3) | 핫딜(2) | 커뮤니티(2) | 동네(1)     │
│  ────────────────────────────────────────────────────    │
│  [상품 결과 카드들...]                                   │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 3.4 SearchPage에서의 자동완성 인터랙션

**시나리오 1: 타이핑 중 자동완성 사용**
```
1. SearchPage 도착 (기존 검색 결과가 아래에 표시됨)
2. 검색바에 "돼지" 입력
3. 200ms 후 자동완성 드롭다운 등장 (기존 결과 위에 오버레이)
4. ↓ 키로 "📦 돼지고기 앞다리" 선택
5. Enter → suggested_action에 따라 라우팅 or 모달 오픈
6. 드롭다운 닫힘, 검색 결과 갱신
```

**시나리오 2: 빈 입력에서 포커스**
```
1. 검색바 클릭/포커스
2. 드롭다운에 최근 검색어 + 🔥 인기 검색어 표시
3. "🕐 삼겹살" 클릭 → 검색어로 재검색
```

**시나리오 3: 드롭다운 없이 직접 검색**
```
1. "새우" 입력 후 바로 Enter (자동완성 항목 선택 안 함)
2. activeIndex === -1 → 일반 검색 실행
3. URL 갱신: ?q=새우 → 검색 결과 표시
```

### 3.5 SearchPage variant 차이점

| 동작 | Header (`variant="header"`) | SearchPage (`variant="page"`) |
|------|---------------------------|-------------------------------|
| 검색 실행 후 | searchOpen=false, 라우팅 | URL params 갱신 (같은 페이지) |
| 드롭다운 위치 | Header 아래 고정 (absolute) | 검색바 바로 아래 (relative flow 내 absolute) |
| 키워드 클릭 | 라우팅 + searchOpen=false | 라우팅 or URL params 갱신 |
| 상품 클릭 | 모달 or 라우팅 | 모달 or 라우팅 (동일) |
| 검색 후 input 초기화 | ✅ setSearchQuery('') | ❌ 입력값 유지 (re-search 가능) |
| 최근 검색 표시 | ✅ | ✅ |
| 인기 검색어 표시 | ✅ | ✅ |

---

## 4. 공통 Autocomplete 컴포넌트 설계

### 4.1 파일 위치

```
packages/website/frontend/src/components/common/
├── SearchAutocomplete.jsx          ← 새 컴포넌트
├── SearchAutocomplete.module.css   ← 새 스타일
└── ... (기존 common 컴포넌트들)
```

### 4.2 Props 인터페이스

```typescript
interface SearchAutocompleteProps {
  /** 표시 변형: "header"는 compact, "page"는 full-width */
  variant: 'header' | 'page';

  /** input placeholder 텍스트 */
  placeholder?: string;

  /** 초기 검색어 (SearchPage에서 URL ?q= 값 전달) */
  initialValue?: string;

  /** input 자동 포커스 여부 */
  autoFocus?: boolean;

  /** 검색 실행 콜백 (Enter 또는 전체 검색 클릭) */
  onSearch: (query: string) => void;

  /** 키워드 항목 클릭 콜백 */
  onKeywordClick: (keyword: KeywordItem) => void;

  /** 상품 항목 클릭 콜백 */
  onProductClick: (product: ProductItem) => void;

  /** 최근 검색어 클릭 콜백 */
  onRecentClick?: (query: string) => void;

  /** 검색 후 input 값 초기화 여부 (default: false) */
  clearOnSearch?: boolean;

  /** 닫기 버튼 표시 여부 (Header에서 사용) */
  showClose?: boolean;

  /** 닫기 콜백 */
  onClose?: () => void;

  /** 외부에서 inputValue를 동기화할 때 (controlled mode) */
  value?: string;
  onChange?: (value: string) => void;

  /** CSS 클래스 오버라이드 */
  className?: string;
  dropdownClassName?: string;
}
```

### 4.3 내부 상태 관리

```jsx
function SearchAutocomplete({
  variant = 'page',
  placeholder = '검색...',
  initialValue = '',
  autoFocus = false,
  onSearch,
  onKeywordClick,
  onProductClick,
  onRecentClick,
  clearOnSearch = false,
  showClose = false,
  onClose,
  className,
  dropdownClassName,
}) {
  // ── 내부 상태 ──
  const [inputValue, setInputValue]       = useState(initialValue);
  const [keywords, setKeywords]           = useState([]);
  const [products, setProducts]           = useState([]);
  const [totalKeywords, setTotalKeywords] = useState(0);
  const [totalProducts, setTotalProducts] = useState(0);
  const [trending, setTrending]           = useState([]);
  const [showDropdown, setShowDropdown]   = useState(false);
  const [activeIndex, setActiveIndex]     = useState(-1);

  // ── Refs ──
  const debounceRef  = useRef(null);
  const containerRef = useRef(null);
  const inputRef     = useRef(null);

  // ── Store ──
  const recentSearches = useStore((st) => st.recentSearches);
  const addRecentSearch = useStore((st) => st.addRecentSearch);
  const { openMartModal, openHotdealModal, openProductModal } = useModalStore();

  // ... (구현 상세는 아래)
}
```

### 4.4 키보드 내비게이션

```
키              동작
───             ────
ArrowDown       activeIndex++ (0 → 마지막 → 처음으로 순환)
ArrowUp         activeIndex-- (마지막 → 처음 → 마지막으로 순환)
Enter           activeIndex >= 0 → 해당 항목 클릭 핸들러 실행
                activeIndex === -1 → onSearch(inputValue)
Escape          드롭다운 닫기 (showDropdown = false)
Tab             드롭다운 닫기 (접근성: 포커스 이동 허용)
```

**activeIndex 계산:**
```
allItems = [...keywords, ...products]
─────────────────────────────────────
index 0   → keywords[0]  (키워드 섹션)
index 1   → keywords[1]
index 2   → keywords[2]
index 3   → products[0]  (상품 섹션)
index 4   → products[1]
index 5   → products[2]
...
```

빈 입력(`inputValue === ''`)일 때는 최근 검색어 목록을 activeIndex로 내비게이션한다.

### 4.5 debounce 전략

```
입력 발생 → debounceRef.current 취소 → 200ms 타이머 시작
  ├── 200ms 내에 추가 입력 → 타이머 리셋
  └── 200ms 경과 → searchService.autocomplete(value) 호출
       ├── 성공 → setKeywords, setProducts 업데이트
       └── 실패 → 무시 (기존 상태 유지)
```

### 4.6 하이라이트 매칭

```jsx
function highlightMatch(text, query) {
  if (!query || !text) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <strong>{text.slice(idx, idx + query.length)}</strong>
      {text.slice(idx + query.length)}
    </>
  );
}
```

이 함수는 `SearchAutocomplete.jsx` 내부에 정의하거나, `utils/helpers.js`로 이동하여 재사용한다.

### 4.7 드롭다운 렌더링 구조 (JSX)

```jsx
{showDropdown && hasDropdownContent && (
  <div className={`${s.dropdown} ${dropdownClassName || ''}`}>
    {/* CASE 1: 자동완성 결과 있음 → 2섹션 표시 */}
    {hasAcResults ? (
      <>
        {keywords.length > 0 && (
          <>
            <div className={s.sectionLabel}>키워드</div>
            {keywords.map((kw, i) => (
              <button
                key={`kw-${kw.id}`}
                className={`${s.item} ${i === activeIndex ? s.itemActive : ''}`}
                onClick={() => handleKeywordSelect(kw)}
                onMouseEnter={() => setActiveIndex(i)}
              >
                <span className={s.iconEmoji}>🔍</span>
                <div className={s.content}>
                  <span className={s.word}>{highlightMatch(kw.word, inputValue)}</span>
                  {kw.matched_synonym && (
                    <span className={s.hint}>← "{kw.matched_synonym}" 포함</span>
                  )}
                  <span className={s.path}>{kw.category_path}</span>
                </div>
              </button>
            ))}
          </>
        )}

        {keywords.length > 0 && products.length > 0 && <div className={s.divider} />}

        {products.length > 0 && (
          <>
            <div className={s.sectionLabel}>상품</div>
            {products.map((p, i) => {
              const idx = keywords.length + i;
              return (
                <button
                  key={`p-${p.id}`}
                  className={`${s.item} ${idx === activeIndex ? s.itemActive : ''}`}
                  onClick={() => handleProductSelect(p)}
                  onMouseEnter={() => setActiveIndex(idx)}
                >
                  <span className={s.iconEmoji}>{p.icon || '📦'}</span>
                  <div className={s.content}>
                    <span className={s.word}>{highlightMatch(p.name, inputValue)}</span>
                    <span className={s.meta}>
                      {p.unit} {p.current_price ? `· ${fmt(p.current_price)}원` : ''}
                    </span>
                  </div>
                </button>
              );
            })}
          </>
        )}

        {(totalKeywords > 3 || totalProducts > 5) && (
          <div className={s.footer} onClick={() => handleFullSearch()}>
            🔍 "{inputValue}" 전체 검색 결과 보기 ({totalKeywords + totalProducts}건)
          </div>
        )}
      </>
    ) : inputValue ? (
      /* CASE 2: 검색어 있는데 결과 없음 */
      <div className={s.empty}>
        <span>😅 "{inputValue}"에 대한 결과가 없습니다.</span>
        {trending.length > 0 && (
          <div className={s.trendingGrid}>
            {trending.map(t => (
              <button key={t.word} className={s.trendBtn}
                onClick={() => { setInputValue(t.word); fetchAutocomplete(t.word); }}>
                🔥 {t.word}
              </button>
            ))}
          </div>
        )}
      </div>
    ) : (
      /* CASE 3: 빈 입력 + 포커스 → 최근 검색 + 인기 키워드 */
      <>
        {recentList.length > 0 && (
          <>
            <div className={s.sectionLabel}>최근 검색</div>
            {recentList.slice(0, 5).map((item, i) => (
              <button key={i}
                className={`${s.item} ${i === activeIndex ? s.itemActive : ''}`}
                onClick={() => handleRecentSelect(item)}
                onMouseEnter={() => setActiveIndex(i)}>
                <Clock size={14} className={s.itemIcon} />
                <span>{item}</span>
              </button>
            ))}
          </>
        )}
        {trending.length > 0 && (
          <>
            {recentList.length > 0 && <div className={s.divider} />}
            <div className={s.sectionLabel}>🔥 인기 검색어</div>
            {trending.map((t) => (
              <button key={t.word} className={s.item}
                onClick={() => { setInputValue(t.word); addRecentSearch(t.word); fetchAutocomplete(t.word); }}>
                <span className={s.iconEmoji}>{t.icon || '🔥'}</span>
                <span>{t.word}</span>
              </button>
            ))}
          </>
        )}
      </>
    )}
  </div>
)}
```

### 4.8 CSS 구조 (SearchAutocomplete.module.css)

```css
/* 컨테이너 */
.container {
  position: relative;
  width: 100%;
}

/* 인풋 래퍼 */
.inputWrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.input {
  flex: 1;
  padding: 8px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-size: 0.9rem;
  outline: none;
}
.input:focus {
  border-color: var(--accent);
}

/* variant="page" 일 때 더 큰 인풋 */
.inputPage {
  padding: 12px 14px 12px 40px;
  font-size: 1rem;
}

/* 드롭다운 */
.dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 4px;
  background: var(--bg2);
  border: 1px solid var(--border2);
  border-radius: var(--radius, 8px);
  box-shadow: var(--shadow-lg, 0 8px 32px rgba(0,0,0,.12));
  max-height: 320px;
  overflow-y: auto;
  padding: 4px;
  z-index: 200;
}

/* 드롭다운 항목 */
.item { /* Header.module.css의 .dropItem과 동일 */ }
.itemActive { /* .dropItemActive와 동일 */ }

/* 섹션/구분선 */
.sectionLabel { /* .acSectionLabel과 동일 */ }
.divider { /* .acDivider와 동일 */ }

/* 콘텐츠 */
.iconEmoji { /* .acIconEmoji와 동일 */ }
.content { /* .acContent와 동일 */ }
.word { /* .acWord와 동일 */ }
.hint { /* .acHint와 동일 */ }
.path { /* .acPath와 동일 */ }
.meta { /* .acMeta와 동일 */ }

/* 하단/빈 결과/트렌딩 */
.footer { /* .acFooter와 동일 */ }
.empty { /* .acEmpty와 동일 */ }
.trendingGrid { /* .acTrending과 동일 */ }
.trendBtn { /* .acTrendBtn과 동일 */ }
```

> **참고:** CSS는 Header.module.css에서 `ac*` 접두사 클래스들을 그대로 가져오되, 이름만 간결하게 변경한다. 이는 Header.module.css에서 해당 스타일을 제거하고 SearchAutocomplete.module.css로 이전한다는 의미가 **아니다** — 점진적 마이그레이션을 위해 Header는 당분간 자체 스타일을 유지하고, SearchAutocomplete는 독립적인 스타일을 가진다. 향후 Header도 SearchAutocomplete를 사용하게 되면 Header.module.css에서 중복 스타일을 제거한다.

---

## 5. API 변경 사항

### 5.1 자동완성 API 응답 보강 (권장)

**현재 `/api/search/autocomplete` 상품 응답:**

```json
{
  "type": "product",
  "id": 42,
  "name": "삼겹살 (국산, 냉장)",
  "unit": "100g",
  "icon": "🥩",
  "current_price": 2980,
  "original_price": 3500,
  "discount_pct": 15,
  "source_type": "mart_crawl",
  "has_baseline": true,
  "suggested_action": "product_modal"
}
```

**개선 후 응답 (추가 필드):**

```json
{
  "type": "product",
  "id": 42,
  "name": "삼겹살 (국산, 냉장)",
  "unit": "100g",
  "icon": "🥩",
  "current_price": 2980,
  "original_price": 3500,
  "discount_pct": 15,
  "source_type": "mart_crawl",
  "has_baseline": true,
  "suggested_action": "product_modal",
  // ── 추가 필드 ──
  "image_url": "https://...",         // ← NEW: Product.image_url
  "category_id": "meat.pork.belly",   // ← NEW: Product.category_id
  "category_path": "축산 > 돼지고기 > 삼겹살",  // ← NEW: 빌드된 경로
  "source": "emart",                  // ← NEW: DiscountHistory.source
  "source_url": "https://...",        // ← NEW: DiscountHistory.source_url
  "valid_from": "2025-01-15",         // ← NEW: DiscountHistory.valid_from
  "valid_to": "2025-01-22"            // ← NEW: DiscountHistory.valid_to
}
```

**백엔드 변경 위치:** `packages/db-admin/backend/storage/db.py` — `search_autocomplete()` 메서드의 Stage 4 (상품 결과 빌드)

**변경 내용:**

```python
# 기존 product_results.append() 부분에 필드 추가
product_results.append({
    "type": "product",
    "match_type": "product_name",
    "id": p.id,
    "name": p.name,
    "category_id": p.category_id,       # 기존
    "unit": p.unit,                      # 기존
    "icon": cat.icon if cat else "",     # 기존
    "current_price": current_price,      # 기존
    "original_price": original_price,    # 기존
    "discount_pct": discount_pct,        # 기존
    "source_type": source_type,          # 기존
    "has_baseline": has_baseline,        # 기존
    "suggested_action": suggested_action,# 기존
    # ── 추가 ──
    "image_url": p.image_url or "",
    "category_path": self._build_category_path(session, p.category_id),
    "source": latest_discount.source if latest_discount else "",
    "source_url": latest_discount.source_url if latest_discount else "",
    "valid_from": latest_discount.valid_from.strftime("%Y-%m-%d") if latest_discount and latest_discount.valid_from else "",
    "valid_to": latest_discount.valid_to.strftime("%Y-%m-%d") if latest_discount and latest_discount.valid_to else "",
})
```

**성능 영향:** 미미함. `latest_discount`는 이미 쿼리하고 있고, `p.image_url`은 Product 모델에 이미 로드된 필드, `_build_category_path`도 이미 키워드 섹션에서 사용 중인 메서드.

### 5.2 상품 상세 API (기존 활용)

`GET /api/products/{product_id}` 엔드포인트는 이미 존재하며 다음을 반환:

```json
{
  "id": 42,
  "name": "삼겹살 (국산, 냉장)",
  "icon": "🥩",
  "cat": "삼겹살",
  "unit": "100g",
  "avg": 3200,
  "cur": 2980,
  "low": 2500,
  "high": 4200,
  "price_tier": "저렴",
  "img": "https://...",
  "stores": [...],
  "stats": {...},
  "attributes": {}
}
```

**활용:** ProductQuickView의 Phase 2에서 이 API를 호출한다. 추가 변경 없이 사용 가능하지만, 할인 기간(`valid_from`, `valid_to`)과 출처 URL(`source_url`)은 현재 이 응답에 포함되지 않는다.

### 5.3 상품 상세 API 보강 (선택사항)

자동완성 API 보강(5.1)으로 대부분의 데이터가 해결되지만, Phase 2 로딩에서 할인 기간과 출처 URL도 보여주려면 `get_product_detail()` 응답에 추가 필드가 필요하다:

**변경 위치:** `packages/db-admin/backend/storage/db.py` — `get_product_detail()` 메서드

```python
# 기존 return dict에 추가
return {
    # ... 기존 필드들 ...
    "description": p.description or "",          # ← NEW
    "category_path": self._build_category_path(session, p.category_id),  # ← NEW
    "source_type": p.source_type or "unknown",   # ← NEW
    "source_url": latest.source_url if latest else "",  # ← NEW
    "source": latest.source if latest else "",    # ← NEW
    "valid_from": latest.valid_from.strftime("%Y-%m-%d") if latest and latest.valid_from else "",  # ← NEW
    "valid_to": latest.valid_to.strftime("%Y-%m-%d") if latest and latest.valid_to else "",  # ← NEW
    "original_price": latest.original_price if latest else None,  # ← NEW
}
```

여기서 `latest`는 최신 `DiscountHistory` 레코드로, `_get_store_prices` 내부에서 이미 쿼리되고 있으므로 변수를 재활용하거나 별도 쿼리를 추가한다.

### 5.4 프론트엔드 서비스 추가

**`productService.js`에 `getDetail` 메서드 추가 (또는 신규 생성):**

```javascript
// packages/website/frontend/src/services/productService.js

import { api } from './api';

export const productService = {
  async getDetail(productId) {
    const res = await api.get(`/api/products/${productId}`);
    return res.json();
  },
};
```

> 이미 `searchService.js` 등에서 `api` 모듈을 import하고 있으므로, 동일 패턴으로 작성한다. `GET /api/products/:id`는 이미 존재하는 엔드포인트이므로 새 라우트는 필요 없다.

---

## 6. 구현 단계 및 파일 변경 목록

### Phase 1: ProductQuickView 리디자인 (우선순위: 높음)

| # | 작업 | 파일 | 복잡도 | 비고 |
|---|------|------|--------|------|
| 1-1 | 자동완성 API 응답에 `image_url`, `category_id`, `category_path`, `source`, `source_url`, `valid_from`, `valid_to` 추가 | `packages/db-admin/backend/storage/db.py` (search_autocomplete) | ⭐⭐ 중 | 기존 변수 재활용, 필드 추가만 |
| 1-2 | `productService.js` 생성 (또는 기존 서비스에 `getDetail` 추가) | `packages/website/frontend/src/services/productService.js` | ⭐ 하 | 3줄 메서드 |
| 1-3 | `get_product_detail()` 응답에 `category_path`, `description`, `source_url`, `valid_from`, `valid_to`, `original_price` 추가 | `packages/db-admin/backend/storage/db.py` (get_product_detail) | ⭐⭐ 중 | latest discount 쿼리 추가 |
| 1-4 | `ProductQuickView.jsx` 전면 리디자인 | `packages/website/frontend/src/components/modals/ProductQuickView.jsx` | ⭐⭐⭐ 상 | 79줄 → ~120줄, 2단계 로딩 |
| 1-5 | `ProductQuickView.module.css` 스타일 확장 | `packages/website/frontend/src/components/modals/ProductQuickView.module.css` | ⭐⭐ 중 | MartProductModal 스타일 차용 |
| 1-6 | 수동 테스트: 자동완성 → product_modal → 정보 확인 | — | ⭐ 하 | |

### Phase 2: 공통 Autocomplete 컴포넌트 (우선순위: 높음)

| # | 작업 | 파일 | 복잡도 | 비고 |
|---|------|------|--------|------|
| 2-1 | `SearchAutocomplete.jsx` 생성 | `packages/website/frontend/src/components/common/SearchAutocomplete.jsx` | ⭐⭐⭐ 상 | Header 로직 추출 (~150줄) |
| 2-2 | `SearchAutocomplete.module.css` 생성 | `packages/website/frontend/src/components/common/SearchAutocomplete.module.css` | ⭐⭐ 중 | Header.module.css 스타일 복사+정리 |
| 2-3 | `highlightMatch` 함수를 `utils/helpers.js`로 이동 | `packages/website/frontend/src/utils/helpers.js` | ⭐ 하 | |

### Phase 3: SearchPage 통합 (우선순위: 높음)

| # | 작업 | 파일 | 복잡도 | 비고 |
|---|------|------|--------|------|
| 3-1 | `SearchPage.jsx` — 기존 `<form>` + `<input>`을 `<SearchAutocomplete variant="page">` 로 교체 | `packages/website/frontend/src/pages/Search/SearchPage.jsx` | ⭐⭐ 중 | form 제거, 콜백 연결 |
| 3-2 | `SearchPage.module.css` — searchForm/searchInput/formIcon 스타일 정리 (SearchAutocomplete로 이관) | `packages/website/frontend/src/pages/Search/SearchPage.module.css` | ⭐ 하 | |
| 3-3 | 수동 테스트: SearchPage에서 자동완성 동작 확인 | — | ⭐ 하 | |

### Phase 4: Header 마이그레이션 (우선순위: 보통 — 선택사항)

| # | 작업 | 파일 | 복잡도 | 비고 |
|---|------|------|--------|------|
| 4-1 | `Header.jsx` — 인라인 자동완성 로직을 `<SearchAutocomplete variant="header">` 로 교체 | `packages/website/frontend/src/components/layout/Header.jsx` | ⭐⭐⭐ 상 | ~150줄 제거, 컴포넌트 사용 |
| 4-2 | `Header.module.css` — ac* 스타일 제거 (SearchAutocomplete.module.css로 이관 완료 후) | `packages/website/frontend/src/components/layout/Header.module.css` | ⭐ 하 | 121-134줄 제거 |
| 4-3 | 회귀 테스트: Header 검색 기능 정상 동작 확인 | — | ⭐⭐ 중 | |

### 구현 순서 권장

```
Phase 1 (ProductQuickView)  ←── 독립 작업, 사용자 불만 해소 우선
    ↓
Phase 2 (공통 컴포넌트)     ←── SearchPage 통합의 전제 조건
    ↓
Phase 3 (SearchPage)        ←── Phase 2 완료 후 즉시
    ↓
Phase 4 (Header 마이그레이션) ←── 선택적. 리팩토링이므로 기능 변화 없음
```

**총 예상 작업량:**
- Phase 1: 3-4시간
- Phase 2: 3-4시간
- Phase 3: 1-2시간
- Phase 4: 2-3시간
- **합계: 9-13시간 (1.5-2일)**

---

## 7. 접근성 및 모바일 고려사항

### 7.1 접근성 (A11y)

| 항목 | 구현 방법 |
|------|-----------|
| ARIA role | 드롭다운에 `role="listbox"`, 항목에 `role="option"` |
| aria-activedescendant | input에 현재 activeIndex 항목의 id 연결 |
| aria-expanded | input에 `aria-expanded={showDropdown}` |
| aria-label | 검색 input에 `aria-label="통합 검색"` |
| 키보드 접근 | Tab으로 드롭다운 밖으로 이동 가능 (Escape와 별개) |
| 스크린 리더 | 섹션 레이블("키워드", "상품")이 시각적으로만 표시되므로 `aria-label` 추가 |

### 7.2 모바일 대응

**SearchAutocomplete:**
- 모바일에서 드롭다운은 화면 하단까지 확장 (`max-height: 60vh`)
- 항목 터치 영역 최소 44px (현재 `padding: 10px 12px`은 충분)
- `position: fixed` 대신 `position: absolute`로 스크롤 내 자연스러운 위치

**ProductQuickView:**
- 모바일에서 이미지 크기 `150px × 150px`로 축소
- 버튼 2열 레이아웃 → 1열 스택으로 변경 (`@media (max-width: 480px)`)
- 모달 자체가 전체 화면에 가깝게 (`max-height: 90vh; overflow-y: auto`)

```css
@media (max-width: 480px) {
  .img, .imgPlaceholder {
    width: 150px;
    height: 150px;
  }
  .compareBtn,
  .categoryBtn,
  .cartBtn {
    flex: 1 1 100%;  /* 1열 스택 */
  }
}
```

### 7.3 성능 고려

| 항목 | 전략 |
|------|------|
| 자동완성 debounce | 200ms (현재와 동일) |
| 상품 상세 API 캐싱 | `React.useMemo` 또는 `Map` 캐시로 동일 product_id 재호출 방지 |
| 이미지 로딩 | `<img loading="lazy" />` + placeholder 표시 |
| 번들 크기 | SearchAutocomplete는 Header와 SearchPage 모두에서 import → 코드 분할 불필요 (공통 chunk) |
| 드롭다운 리렌더링 | `React.memo`로 항목 컴포넌트 감싸기 (선택적 최적화) |

---

## 부록: 변경 파일 체크리스트

```
packages/
├── db-admin/backend/storage/
│   └── db.py
│       ├── search_autocomplete() — 응답 필드 추가 (image_url, category_path, source, etc.)
│       └── get_product_detail() — 응답 필드 추가 (category_path, valid_from/to, etc.)
│
├── website/backend/api/routes/
│   └── products.py — 변경 없음 (기존 엔드포인트 활용)
│
└── website/frontend/src/
    ├── components/
    │   ├── common/
    │   │   ├── SearchAutocomplete.jsx       ← 신규
    │   │   └── SearchAutocomplete.module.css ← 신규
    │   ├── layout/
    │   │   ├── Header.jsx                   ← Phase 4에서 리팩토링
    │   │   └── Header.module.css            ← Phase 4에서 스타일 정리
    │   └── modals/
    │       ├── ProductQuickView.jsx          ← 전면 리디자인
    │       └── ProductQuickView.module.css   ← 스타일 확장
    ├── pages/Search/
    │   ├── SearchPage.jsx                   ← 검색바 교체
    │   └── SearchPage.module.css            ← 스타일 정리
    ├── services/
    │   └── productService.js                ← 신규 (또는 기존 서비스에 추가)
    └── utils/
        └── helpers.js                       ← highlightMatch 추가
```
