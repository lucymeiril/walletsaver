# 검색 결과 라우팅 알고리즘 기획서

## 3인 전문가 토론 기반 설계

---

## 1. 문제 정의

현재 자동완성 결과 클릭 시:
- **키워드 클릭** → `/search?q=삼겹살` (범용 검색 — 카테고리 비교가 아님)
- **상품 클릭** → `/price/62` (개별 상품 — 마트 상품인데도 물가비교 페이지로)

**문제:** 마트에서 크롤링한 `"보먹돼 목심 100G/돼지고기(목살)"`을 클릭하면 `/price/62`로 이동하는데,
이 상품은 기준가(baseline price)가 없어 0원으로 표시. 마트 할인 상품이므로 마트 상품 모달로 열어야 한다.

---

## 2. 전문가 토론

### 토론 1: 상품 소스 분류 — "이건 마트 상품인가, 비교 대상인가?"

**B (API 설계자):** Product 테이블에 `source_type` 필드를 추가하자. 생성 시점에 소스를 기록.

**C (UX 기획자):** 사용자 관점에선 소스가 중요한 게 아니라 "이걸 클릭하면 뭘 볼 수 있나"가 중요하다.
baseline_price가 있으면 비교 가능, discount_history만 있으면 마트 딜.

**A (프론트 아키텍트):** 백엔드에서 `suggested_action`을 내려주는 게 깔끔하다. 프론트는 그냥 따르면 된다.

#### 합의사항: Product에 source_type 추가 + API에 suggested_action

```python
# models.py 수정
class Product(Base):
    # 기존 필드 유지
    source_type = Column(String(20), default="unknown")
    # "mart_crawl" | "community_deal" | "baseline" | "user_submitted" | "unknown"

# 분류 로직
def classify_product_source(product, session):
    """DB 데이터 기반으로 source_type 결정"""
    has_baseline = session.query(BaselinePrice).filter_by(product_id=product.id).first()
    has_discount = session.query(DiscountHistory).filter_by(product_id=product.id).first()
    has_hotdeal = session.query(HotdealPrice).filter_by(product_id=product.id).first()
    
    if has_baseline:
        return "baseline"  # 기준가 있음 → 물가비교 대상
    
    if has_discount:
        source = has_discount.source  # "emart", "homeplus" 등
        if source in ("emart", "homeplus", "lottemart"):
            return "mart_crawl"
        return "community_deal"
    
    if has_hotdeal:
        return "community_deal"
    
    return "unknown"
```

---

### 토론 2: 자동완성 API 응답 확장

**B:** 프론트가 라우팅 결정을 하려면 추가 정보가 필요하다.

**A:** 너무 많은 정보를 내리면 응답이 느려진다. 최소한의 메타데이터만.

**C:** `suggested_action`과 최소 메타데이터면 충분하다.

#### 합의사항: 확장된 자동완성 응답

```json
{
  "keywords": [
    {
      "type": "keyword",
      "match_type": "keyword_direct",
      "id": 113,
      "word": "앞다리",
      "category_id": "livestock.pork.front_leg",
      "category_path": "축산물 > 돼지고기 > 앞다리",
      "search_count": 42,
      "suggested_action": "category_page",
      "action_url": "/price/category/livestock.pork.front_leg"
    }
  ],
  "products": [
    {
      "type": "product",
      "match_type": "product_name",
      "id": 62,
      "name": "[냉장] 앞다리살 보쌈/수육용 1kg",
      "category_id": "livestock.pork.front_leg",
      "source_type": "mart_crawl",
      "source": "emart",
      "current_price": 12900,
      "original_price": 16900,
      "discount_pct": 24,
      "suggested_action": "mart_modal",
      "has_baseline": false
    },
    {
      "type": "product",
      "match_type": "product_name",
      "id": 8,
      "name": "앞다리살",
      "category_id": "livestock.pork.front_leg",
      "source_type": "baseline",
      "current_price": 14500,
      "suggested_action": "price_page",
      "has_baseline": true
    }
  ]
}
```

**suggested_action 결정 로직:**

```python
def determine_action(item_type, item):
    if item_type == "keyword":
        if item.category_id:
            return "category_page"   # 카테고리가 있으면 비교 페이지
        else:
            return "search_page"     # 카테고리 없으면 검색 결과
    
    elif item_type == "product":
        if item.source_type == "mart_crawl":
            return "mart_modal"      # 마트 크롤링 상품 → 모달
        elif item.source_type == "community_deal":
            return "hotdeal_modal"   # 커뮤니티 핫딜 → 핫딜 모달/링크
        elif item.source_type == "baseline" or item.has_baseline:
            return "price_page"      # 기준가 있는 상품 → 물가비교
        else:
            return "product_modal"   # 기타 → 기본 상품 모달
```

---

### 토론 3: 라우팅 의사결정 트리 — 완전판

**A:** 모든 경우를 빠짐없이 정리하자. 클릭 위치(Header/Home/Price/Mart/...)도 고려.

**C:** 현재 페이지 컨텍스트에 따라 행동이 달라져야 한다. MartPage에서 검색하면 마트 내에서 필터링.

**B:** 컨텍스트 정보를 `useNavigationContext()` 훅으로 관리하자.

#### 합의사항: 완전 라우팅 결정 트리

```
사용자 입력:
├── Enter 키 (텍스트 직접 검색)
│   └── 항상 → /search?q={query} (통합 검색 결과)
│
├── 키워드 클릭
│   ├── category_id 있음
│   │   └── → /price/category/{categoryId} (카테고리 비교 페이지)
│   └── category_id 없음
│       └── → /search?q={word} (통합 검색 결과)
│
├── 상품 클릭
│   ├── suggested_action == "mart_modal"
│   │   └── → 마트 상품 모달 열기 (현재 페이지 유지)
│   │       └── 모달 내: 이미지, 할인가, 원가, 할인율, 마트명, 기간, 온라인몰 링크
│   │
│   ├── suggested_action == "hotdeal_modal"
│   │   └── → 핫딜 모달 열기 (현재 페이지 유지)
│   │       └── 모달 내: 제목, 가격, 소스, 링크, 커뮤니티 반응
│   │
│   ├── suggested_action == "price_page"
│   │   └── → /price/{productId} (물가비교 상세)
│   │
│   └── suggested_action == "product_modal"
│       └── → 기본 상품 모달 (이름, 가격, 카테고리 정보)
│
└── 포커스(클릭 없이 인풋 포커스)
    └── 인기 검색어 드롭다운 표시

페이지 컨텍스트별 추가 행동:
├── MartPage에서 검색
│   └── 마트 상품만 필터링하여 표시, 마트 모달 우선
├── PricePage에서 검색
│   └── 키워드 → 현재 페이지 내에서 카테고리 전환
├── HomePage에서 검색
│   └── 기본 라우팅 적용
└── 기타 페이지 (Header 검색)
    └── 기본 라우팅 적용
```

---

### 토론 4: 모달 시스템 설계

**A:** MartPage에 이미 마트 상품 모달이 있다. 이걸 공유 컴포넌트로 추출하자.

**C:** 글로벌 모달 매니저가 필요하다. 어느 페이지에서든 모달을 열 수 있어야 하니까.

**B:** 모달이 열릴 때 추가 데이터를 fetch해야 한다. 같은 카테고리 상품 목록 등.

#### 합의사항: 글로벌 모달 시스템

```
컴포넌트 구조:
src/
├── components/
│   ├── modals/
│   │   ├── ModalManager.jsx        ← 글로벌 모달 관리자
│   │   ├── MartProductModal.jsx     ← 마트 상품 모달 (MartPage에서 추출)
│   │   ├── HotdealModal.jsx         ← 핫딜 모달
│   │   └── ProductQuickView.jsx     ← 기본 상품 빠른보기
│   └── layout/
│       └── Header.jsx               ← 검색바
├── hooks/
│   └── useModal.js                  ← 모달 상태 관리 훅
└── stores/
    └── modalStore.js                ← Zustand 모달 상태
```

**Zustand 모달 스토어:**
```javascript
// stores/modalStore.js
import { create } from 'zustand';

const useModalStore = create((set) => ({
  activeModal: null,    // "mart" | "hotdeal" | "product" | null
  modalData: null,      // 모달에 전달할 데이터
  
  openMartModal: (product) => set({ 
    activeModal: "mart", 
    modalData: product 
  }),
  
  openHotdealModal: (deal) => set({ 
    activeModal: "hotdeal", 
    modalData: deal 
  }),
  
  openProductModal: (product) => set({ 
    activeModal: "product", 
    modalData: product 
  }),
  
  closeModal: () => set({ 
    activeModal: null, 
    modalData: null 
  }),
}));
```

**ModalManager (App 레벨):**
```jsx
// components/modals/ModalManager.jsx
function ModalManager() {
  const { activeModal, modalData, closeModal } = useModalStore();
  
  if (!activeModal) return null;
  
  switch (activeModal) {
    case "mart":
      return <MartProductModal data={modalData} onClose={closeModal} />;
    case "hotdeal":
      return <HotdealModal data={modalData} onClose={closeModal} />;
    case "product":
      return <ProductQuickView data={modalData} onClose={closeModal} />;
    default:
      return null;
  }
}
```

**MartProductModal (MartPage에서 추출):**
```jsx
function MartProductModal({ data, onClose }) {
  // data: { name, image, price, originalPrice, discount, mart, period, onlineUrl, category }
  const diffVsAvg = useCategoryAverage(data.category_id, data.price);
  
  return (
    <Modal onClose={onClose} title={data.name}>
      {data.image && <img src={data.image} alt={data.name} />}
      
      <div className="price-section">
        <span className="sale-price">₩{data.price?.toLocaleString()}</span>
        {data.originalPrice && (
          <span className="original-price">₩{data.originalPrice?.toLocaleString()}</span>
        )}
        {data.discount && <span className="discount-badge">-{data.discount}%</span>}
      </div>
      
      <div className="meta">
        <span>🏬 {data.mart}</span>
        <span>📅 {data.period}</span>
      </div>
      
      {diffVsAvg && (
        <div className="vs-avg">
          카테고리 평균 대비 {diffVsAvg > 0 ? `${diffVsAvg}% 비쌈` : `${Math.abs(diffVsAvg)}% 저렴`}
        </div>
      )}
      
      <div className="actions">
        {data.onlineUrl && <a href={data.onlineUrl} target="_blank">🛒 온라인몰</a>}
        <button onClick={() => navigate(`/price/category/${data.category_id}`)}>
          📊 카테고리 비교
        </button>
      </div>
    </Modal>
  );
}
```

---

### 토론 5: 검색 결과 페이지 강화

**C:** `/search?q=삼겹살`로 가면 지금은 그냥 플랫 목록이다. 카테고리 매칭이 있으면 배너로 안내해야.

**A:** 결과를 타입별로 그룹핑하자. 상품, 핫딜, 마트할인, 커뮤니티 각각 섹션.

**B:** 상단에 카테고리 매칭 배너 + 각 타입별 미리보기 + "더보기" 구조.

#### 합의사항: 검색 결과 페이지 구조

```
/search?q=삼겹살

┌──────────────────────────────────────────┐
│ 🔍 "삼겹살" 검색 결과                     │
├──────────────────────────────────────────┤
│ 💡 "삼겹살" 카테고리를 찾으셨나요?         │
│ [📊 삼겹살 물가비교 보기 →]               │ ← 카테고리 매칭 배너
│ 축산물 > 돼지고기 > 삼겹살                 │
├──────────────────────────────────────────┤
│ 🏬 마트 할인 (12건)                       │
│ ┌────────┐ ┌────────┐ ┌────────┐        │
│ │이마트   │ │롯데마트 │ │홈플러스 │        │
│ │삼겹살   │ │삼겹살   │ │삼겹살   │        │
│ │₩12,900 │ │₩13,500 │ │₩11,900 │        │
│ └────────┘ └────────┘ └────────┘        │
│ [마트 할인 전체보기 →]                     │
├──────────────────────────────────────────┤
│ 🔥 핫딜 (8건)                             │
│ • [뽐뿌] 삼겹살 1kg 무료배송 ₩15,900      │
│ • [에펨] 코스트코 삼겹살 파격할인           │
│ [핫딜 전체보기 →]                          │
├──────────────────────────────────────────┤
│ 📦 상품 정보 (5건)                        │
│ • 삼겹살 — 평균가 ₩1,800/100g             │
│ • 대패삼겹살 — 평균가 ₩2,100/100g         │
│ [상품 전체보기 →]                          │
├──────────────────────────────────────────┤
│ 💬 커뮤니티 (3건)                          │
│ • "오늘 이마트 삼겹살 진짜 핫딜임?"        │
│ [커뮤니티 전체보기 →]                      │
└──────────────────────────────────────────┘
```

---

### 토론 6: 네비게이션 컨텍스트 보존

**A:** 사용자가 MartPage에 있다가 Header에서 검색하면, 마트 컨텍스트를 유지할지 아닐지.

**C:** 직관적으로는 Header 검색은 "사이트 전체 검색", 페이지 내 검색바는 "해당 컨텍스트 내 검색".

**B:** `searchContext` state를 전달하면 된다.

#### 합의사항: 컨텍스트 기반 검색

```javascript
// hooks/useSearchContext.js
function useSearchContext() {
  const location = useLocation();
  
  // 현재 페이지에 따라 검색 컨텍스트 결정
  const getContext = () => {
    if (location.pathname.startsWith('/mart')) return 'mart';
    if (location.pathname.startsWith('/price')) return 'price';
    if (location.pathname.startsWith('/local')) return 'local';
    if (location.pathname.startsWith('/hotdeal')) return 'hotdeal';
    return 'global';  // Header, HomePage
  };
  
  return { context: getContext() };
}

// 검색 클릭 핸들러에서 컨텍스트 활용
function handleAutocompleteClick(item, context) {
  const action = item.suggested_action;
  
  // 마트 페이지 컨텍스트에서는 마트 모달 우선
  if (context === 'mart' && item.type === 'product') {
    openMartModal(item);
    return;
  }
  
  // 물가비교 페이지에서 키워드 클릭 → 페이지 내 카테고리 전환
  if (context === 'price' && item.type === 'keyword' && item.category_id) {
    navigate(`/price/category/${item.category_id}`);
    return;
  }
  
  // 기본 라우팅
  switch (action) {
    case 'category_page':
      navigate(`/price/category/${item.category_id}`);
      break;
    case 'mart_modal':
      openMartModal(item);
      break;
    case 'hotdeal_modal':
      openHotdealModal(item);
      break;
    case 'price_page':
      navigate(`/price/${item.id}`);
      break;
    case 'search_page':
    default:
      navigate(`/search?q=${encodeURIComponent(item.word || item.name)}`);
  }
}
```

---

### 토론 7: URL 스키마 최종 설계

#### 합의사항:

```
기존 (유지):
  /                          → HomePage
  /search?q=삼겹살            → SearchPage (통합 검색 결과)
  /price/:productId          → PricePage (개별 상품 비교)
  /mart                      → MartPage (마트 할인/전단지)
  /hotdeal                   → HotdealPage (핫딜 목록)
  /local                     → LocalPage (동네 물가 지도)
  /community                 → CommunityPage (커뮤니티)

신규:
  /price/category/:categoryId → CategoryComparePage (카테고리별 비교)
  예: /price/category/livestock.pork.belly
  
쿼리 파라미터 (CategoryComparePage):
  ?storage=냉장               → 보관법 필터
  ?origin=국산                → 원산지 필터
  ?sort=price_asc             → 정렬
  ?source=emart               → 소스 필터
  ?view=table                 → 뷰 모드 (card|table)
```

---

## 3. 구현 요약 — 필요한 변경사항

### 백엔드

| 파일 | 변경 |
|------|------|
| `storage/models.py` | Product에 `source_type` 컬럼 추가 |
| `storage/db.py` | `search_autocomplete()` 응답에 `source_type`, `suggested_action`, `has_baseline`, `current_price` 추가 |
| `storage/db.py` | `get_category_comparison()` 신규 메서드 |
| `api/routes/search.py` | autocomplete 응답 확장 |
| `api/routes/products.py` | `GET /products/category/:catId/compare` 신규 엔드포인트 |
| `api/routes/ingestion.py` | `_ensure_product()`에서 `source_type` 설정 |

### 프론트엔드

| 파일 | 변경 |
|------|------|
| `stores/modalStore.js` | 신규 — 글로벌 모달 상태 관리 |
| `components/modals/ModalManager.jsx` | 신규 — 모달 렌더링 |
| `components/modals/MartProductModal.jsx` | MartPage에서 추출 |
| `components/modals/HotdealModal.jsx` | 신규 |
| `components/modals/ProductQuickView.jsx` | 신규 |
| `pages/Price/CategoryCompareView.jsx` | 신규 — 카테고리 비교 페이지 |
| `pages/Price/PricePage.jsx` | 라우터 분기 추가 |
| `components/layout/Header.jsx` | 클릭 핸들러 라우팅 로직 변경 |
| `pages/Home/HomePage.jsx` | 클릭 핸들러 라우팅 로직 변경 |
| `pages/Search/SearchPage.jsx` | 카테고리 배너 + 타입별 그룹핑 |
| `App.jsx` | ModalManager 추가 + 카테고리 라우트 추가 |

### 라우터 변경 (App.jsx):
```jsx
<Routes>
  {/* 기존 */}
  <Route path="/price/:id" element={<PricePage />} />
  
  {/* 신규 — 카테고리 비교 (id보다 위에 배치) */}
  <Route path="/price/category/:categoryId" element={<CategoryComparePage />} />
  
  {/* 기존 유지 */}
  <Route path="/search" element={<SearchPage />} />
  ...
</Routes>

{/* App 최하단에 글로벌 모달 */}
<ModalManager />
```
