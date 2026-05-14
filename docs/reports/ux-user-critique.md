# WalletSavior UX 사용자 관점 비평 보고서

## 전체 평가
**2.8/10 — “절약 서비스”처럼 보이지만, 실제로는 데이터 일관성·상세 연결·개인화 기능이 부족해서 돈 아끼는 실사용 도구로 쓰기 어렵습니다.**

## 🔴 즉시 수정 필요 (사용 불가 수준)
1. **홈페이지 ‘이번 주 마트 세일’은 상품 상세 진입이 아니라 탭 이동만 됩니다.**  
   - 홈 카드 클릭이 `navigate('/mart')`로 끝납니다. 어떤 상품을 눌렀는지 전달하지 않습니다 (`packages/website/frontend/src/pages/Home/HomePage.jsx:740-742`).  
   - 반면 실제 마트 페이지는 같은 카드를 눌렀을 때 상세 모달을 띄울 준비가 되어 있습니다 (`packages/website/frontend/src/pages/Mart/MartPage.jsx:601-602`, `737-829`).  
   - 사용자 입장: “이 상품 뭐지?” 하고 눌렀는데 그냥 마트 탭 첫 화면으로 던져지면 바로 짜증납니다.  
   - **수정:** 홈에서 클릭한 상품/마트 정보를 state로 넘겨 바로 상세 모달을 열거나, 상품 전용 상세 페이지로 연결해야 합니다.

2. **홈페이지 ‘오늘의 물가’는 현재 신뢰하기 어렵습니다.**  
   - 홈은 `/api/dashboard`의 `category_summary`가 비어 있지 않으면 그대로 렌더링합니다 (`packages/website/frontend/src/pages/Home/HomePage.jsx:565-595`).  
   - 그런데 라이브 `/api/dashboard` 응답은 `축산물/농산물/수산물/가공식품`이 전부 0원짜리 기본값이었습니다. 대시보드 조립 로직도 이 값을 그대로 사용합니다 (`packages/website/backend/api/app.py:286-339`).  
   - 반대로 `/api/products/category-summary`를 직접 치면 `etc` 카테고리가 첫 응답으로 나옵니다 (`packages/website/backend/api/routes/products.py:150-239`, 라이브 체크: `GET /api/products/category-summary`).  
   - 사용자 입장: 홈에서는 0원 카드, 직접 API로 보면 `etc`. 둘 다 “절약 기준”으로는 못 믿습니다.  
   - **수정:** 홈 대시보드가 기본값을 노출하지 않게 막고, `etc`를 사용자 친화적 분류로 치환하거나 숨겨야 합니다.

3. **장바구니는 ‘페이지’가 아니라 단순한 FAB 패널이고, 정보가 너무 빈약합니다.**  
   - 앱에는 장바구니 페이지 라우트가 없고, 전역 FAB 패널만 있습니다 (`packages/website/frontend/src/App.jsx:106`, `packages/website/frontend/src/components/common/ShoppingListPanel.jsx:9-109`).  
   - 저장되는 데이터도 `name/price/unit/icon/quantity` 뿐입니다. 매장, 이미지, 카테고리, 원문 링크, 비교가, 선택 이유가 없습니다 (`packages/website/frontend/src/stores/appStore.js:75-95`).  
   - 패널에서도 이름·수량·총액만 보여주고 상세 이동이 불가능합니다 (`packages/website/frontend/src/components/common/ShoppingListPanel.jsx:69-99`).  
   - 사용자 입장: “CJ 비건 프로틴 초코 250ML 수량 1개 2,900원”만 보고 어디서 본 상품인지 기억 못 하면 끝입니다.  
   - **수정:** 이미지, 마트/출처, 카테고리, 단가 비교, 상세 진입 링크를 저장하고 클릭 가능하게 바꿔야 합니다.

4. **찜 목록은 UI 진입조차 사실상 막혀 있습니다.**  
   - 프로필 메뉴의 ‘찜 목록’은 실제 페이지가 아니라 “준비 중” 토스트만 띄웁니다 (`packages/website/frontend/src/components/layout/Header.jsx:157-159`).  
   - 찜 데이터 자체는 로컬 persist로 저장되지만 (`packages/website/frontend/src/stores/appStore.js:53-64`, `149-157`), 그걸 보여주는 `FavoritesDashboard`는 라우트에도 없고 렌더링도 안 됩니다 (`packages/website/frontend/src/components/features/FavoritesDashboard.jsx:17-78`, `packages/website/frontend/src/App.jsx:87-97`).  
   - 사용자 입장: 찜은 되는데 찜 목록 페이지는 없음. 이건 기능이 아니라 반쪽짜리 상태 저장입니다.  
   - **수정:** 별도 찜 페이지를 열고, 로그인 사용자 기준 서버 저장·동기화까지 붙여야 합니다.

5. **가격 알림/알림 기능은 사실상 placeholder입니다.**  
   - 헤더 알림 버튼은 클릭 핸들러가 없습니다 (`packages/website/frontend/src/components/layout/Header.jsx:136-139`).  
   - `notifications`를 store에서 읽지만 store에 해당 상태가 정의돼 있지 않아 항상 0건처럼 동작합니다 (`packages/website/frontend/src/components/layout/Header.jsx:27`, `72-75`; `packages/website/frontend/src/stores/appStore.js:1-162`).  
   - `priceAlerts` 상태는 store에만 있고 실제 UI는 없습니다 (`packages/website/frontend/src/stores/appStore.js:101-111`).  
   - 프로필 메뉴의 ‘가격 알림’도 “준비 중”입니다 (`packages/website/frontend/src/components/layout/Header.jsx:160-162`).  
   - **수정:** 알림 센터·목표가 설정 UI·트리거 조건·읽음 처리까지 최소 흐름을 완성해야 합니다.

6. **커뮤니티의 상품 태깅이 실제 저장되지 않습니다.**  
   - 글쓰기 UI는 `ProductPicker`를 보여주며 상품을 고르게 합니다 (`packages/website/frontend/src/pages/Community/CommunityPage.jsx:369-372`, `packages/website/frontend/src/components/community/ProductPicker.jsx:22-58`).  
   - 그런데 실제 POST payload에는 `product_ids`가 없습니다. `tags`도 없습니다 (`packages/website/frontend/src/pages/Community/CommunityPage.jsx:232-240`).  
   - 백엔드는 `product_ids`를 받을 준비가 되어 있습니다 (`packages/website/backend/api/routes/community.py:211-216`).  
   - 자유 게시판의 `wTag`도 payload에 안 들어가서 태그 UI가 눈속임에 가깝습니다 (`packages/website/frontend/src/pages/Community/CommunityPage.jsx:148`, `381-391`, `232-240`).  
   - **수정:** `product_ids`, `tags`, 자유게시판 태그를 payload에 포함하고 상세 화면에도 노출해야 합니다.

7. **커뮤니티 로그인 UX가 사용자를 속입니다.**  
   - 버튼 문구는 “로그인 후 글쓰기”인데, 클릭하면 로그인 유도 대신 그냥 작성 폼을 엽니다 (`packages/website/frontend/src/pages/Community/CommunityPage.jsx:316-317`, `261-267`).  
   - 결국 제출할 때 백엔드 401을 맞고 에러 토스트만 보게 됩니다 (`packages/website/frontend/src/pages/Community/CommunityPage.jsx:242-255`).  
   - 사용자 입장: 글쓰기가 되는 줄 알고 다 써놓고 마지막에 실패하면 최악입니다.  
   - **수정:** 비로그인 상태에서는 즉시 로그인 모달을 열고, 초안 보존도 해야 합니다.

8. **핫딜 데이터 품질이 낮아 ‘핫딜 점수’나 검증 뱃지를 믿기 어렵습니다.**  
   - UI에는 별도 “핫딜 점수”가 없고, 사실상 할인율 배지와 투표 수만 있습니다 (`packages/website/frontend/src/pages/Hotdeal/HotdealPage.jsx:229-269`, `381-416`).  
   - 라이브 `/api/hotdeals`는 `test item`이 섞여 있고, 다수 항목이 `origPrice=null`, `comments=0`, `views=0`, `votes_hot=0`입니다.  
   - “커뮤니티 검증”도 총 투표 10개 이상일 때만 붙는데, 현재 데이터로는 거의 무의미합니다 (`packages/website/frontend/src/pages/Hotdeal/HotdealPage.jsx:264-266`, `381`).  
   - **수정:** 테스트 데이터 제거, 원가/썸네일/카테고리 보강, 신선도 기준(몇 시간 전 수집인지)과 신뢰도 기준을 분리해야 합니다.

9. **핫딜 댓글/투표는 로그인 신뢰 체계가 약합니다.**  
   - 프론트는 로그인 없이도 핫딜 투표·댓글 입력이 가능합니다 (`packages/website/frontend/src/pages/Hotdeal/HotdealPage.jsx:145-169`, `488-496`).  
   - 댓글 작성 시 프론트가 작성자를 그냥 `'나'`로 넣고 (`packages/website/frontend/src/pages/Hotdeal/HotdealPage.jsx:341-345`), 백엔드도 인증 없이 `author='익명'` 또는 전달된 author를 그대로 저장합니다 (`packages/website/backend/api/routes/hotdeals.py:224-259`).  
   - 사용자 입장: 이 구조에서 “커뮤니티 검증” 배지를 신뢰할 이유가 없습니다.  
   - **수정:** 핫딜 상호작용도 로그인 기반으로 통일하고, 비로그인 사용자는 읽기만 허용해야 합니다.

10. **지역(주유소/식당) 화면은 실시간 데이터와 목업이 섞여 UX가 불안정합니다.**  
   - 반경 선택 UI가 있지만 실제 검색 로직에서 `radius`는 쓰이지 않습니다 (`packages/website/frontend/src/pages/Local/LocalPage.jsx:38`, `543-555`).  
   - 식당 상세 모달 상태 `selectedRest`는 선언만 되고 실제로 set되지 않습니다. 비주유소 클릭은 전부 네이버 장소 모달로 갑니다 (`packages/website/frontend/src/pages/Local/LocalPage.jsx:59`, `415-427`, `811-819`).  
   - `RestDetailContent`는 `mockData`를 직접 가져와 가짜 메뉴/평균가를 계산합니다 (`packages/website/frontend/src/pages/Local/components/RestDetailContent.jsx:1-17`).  
   - 주유소 데이터는 라이브 API 결과가 프론트 mock과 이름/가격이 정확히 일치합니다 (`packages/website/frontend/src/data/mockData.js:17-24`, 라이브 `GET /api/gas/nearby`). 실시간 Opinet 체감은 거의 없습니다.  
   - **수정:** 반경을 실제 쿼리에 반영하고, 식당 상세를 실데이터 기반으로 통일하며, 샘플/시드 데이터는 분리 표시해야 합니다.

## 🟡 불편함 (사용은 가능하나 개선 필요)
1. **홈페이지 첫인상은 예쁘지만 “지금 어디서 뭘 사야 아끼는지”가 한눈에 안 꽂힙니다.**  
   - 히어로 문구는 강하지만, 곧바로 절약 행동으로 이어지는 핵심 CTA가 없습니다 (`packages/website/frontend/src/pages/Home/HomePage.jsx:309-339`).  
   - 돈 아끼려는 사용자는 “삼겹살 어디가 제일 쌈?” 같은 즉답을 원합니다.

2. **홈페이지 주유소 카드는 정보만 보여주고 상세 진입이 없습니다.**  
   - 카드 자체에 클릭 액션이 없습니다 (`packages/website/frontend/src/pages/Home/HomePage.jsx:789-799`).  
   - 사용자는 전체보기로 다시 들어가서 같은 주유소를 찾아야 합니다.

3. **홈페이지 커뮤니티·핫딜 이동은 괜찮지만, 정보 밀도가 낮습니다.**  
   - 핫딜 TOP3는 할인율 기준이라지만 실제 원가가 null인 항목이 많아 근거가 약합니다 (`packages/website/frontend/src/pages/Home/HomePage.jsx:523-551`, 라이브 `/api/dashboard`).  
   - 커뮤니티 인기글도 실제로는 테스트성 글이 상위에 보일 수 있습니다 (라이브 `/api/posts?post_type=hotdeal`).

4. **마트 할인 비교는 이름 맞추기 로직이 너무 단순합니다.**  
   - 비교는 상품명에서 일부 규격 텍스트를 떼고 exact-ish 매칭하는 수준입니다 (`packages/website/frontend/src/pages/Mart/MartPage.jsx:61-91`).  
   - “비비드키친 저당 발사믹드레싱 240g” 같은 상품을 시장 평균과 비교할 정규화가 없습니다.  
   - 그래서 이 기능은 “같아 보이는 문자열” 비교이지, 실제 장보기 비교가 아닙니다.

5. **마트 데이터 자체가 서로 충돌합니다.**  
   - 라이브 `/api/marts`에서는 홈플러스/롯데마트 `deals_count`가 0인데, `/api/marts/homeplus/promotions`에는 상품이 나옵니다.  
   - 사용자는 “홈플러스 할인 없음?”이라고 오해하기 쉽습니다 (`packages/website/backend/api/routes/marts.py:27-43`, `72-106` + 라이브 체크).

6. **물가 비교 메인 페이지는 기본 상품 비교는 되지만, 카테고리 비교는 약합니다.**  
   - `meat.pork.belly` 비교 API 결과가 총 1개 상품, `per_100g=null`로 내려옵니다 (라이브 `GET /api/products/category/meat.pork.belly/compare`).  
   - “삼겹살을 전 마트로 비교”하려는 기대를 충족하지 못합니다.  
   - 관련 핫딜 리스트도 클릭이 안 됩니다 (`packages/website/frontend/src/pages/Price/PricePage.jsx:704-716`).

7. **검색은 작동은 하지만, 결과의 의미가 종종 어긋납니다.**  
   - 자동완성으로 `삼겹살`을 치면 키워드 1순위는 삼겹살이지만, 2순위로 `돼지고기 > 앞다리`가 동의어로 뜹니다 (라이브 `GET /api/search/autocomplete?q=삼겹살`).  
   - 사용자는 관련어 확장보다 “정확한 삼겹살 결과”를 원합니다.  
   - 검색 결과의 `mart` 타입은 실제로 마트 세일 상품인데 탭 라벨은 `동네`입니다 (`packages/website/frontend/src/pages/Search/SearchPage.jsx:15-20`, `95-100`; `packages/website/backend/api/routes/search.py:100-117`).

8. **검색 결과에서 곧바로 목적지로 가기보다 모달 한 번 더 거치는 경우가 많습니다.**  
   - 상품은 `openProductModal`, 마트는 `openMartModal`로 들어갑니다 (`packages/website/frontend/src/pages/Search/SearchPage.jsx:95-100`).  
   - 절약 서비스에서는 “한 단계라도 덜”이 중요합니다.

9. **모바일 IA가 핵심 기능을 놓칩니다.**  
   - 하단 탭에는 홈/핫딜/마트/동네/커뮤니티만 있고, 핵심 기능인 `물가비교`가 빠져 있습니다 (`packages/website/frontend/src/components/layout/BottomNav.jsx:5-11`).  
   - 모바일 사용자는 가격 비교까지 가려면 햄버거나 홈 카테고리를 더 타야 합니다.

10. **회원 기능은 로그인/회원가입은 되지만, 로그인 후 체감 보상이 약합니다.**  
   - 로그인 후 실제로 안정적으로 열리는 건 커뮤니티 작성/댓글/투표 정도입니다 (`packages/website/frontend/src/pages/Community/CommunityPage.jsx:83`, `210-255`, `694-746`).  
   - 프로필 보기/수정, 찜, 알림, 설정은 완성되지 않았습니다 (`packages/website/frontend/src/components/layout/Header.jsx:154-162`).

## 🔵 개선 제안 (있으면 좋은 것)
1. **홈에 ‘오늘 절약 액션 3개’ 카드**  
   - 예: “삼겹살은 롯데마트가 평균보다 3.7% 저렴”, “우유는 오늘 사도 무난”, “계란은 일주일 더 기다리기”.

2. **장바구니를 ‘구매 계획’으로 확장**  
   - 장볼 매장 묶기, 예상 총액, 대체상품 추천, 현재 최저가 기준 재정렬.

3. **찜/알림 서버 저장 및 푸시/이메일 연결**  
   - 로컬 persist만으로는 실사용 가치가 약합니다.

4. **핫딜 신뢰도 분리 표시**  
   - 할인율, 시세 대비, 커뮤니티 반응, 원문 신뢰도, 수집 시각을 별도 배지로 나눠야 합니다.

5. **지역 기능을 ‘가격 지도’ 중심으로 재설계**  
   - 지금은 지도 iframe + 리스트 조합인데, 반경/필터/거리의 의미가 약합니다.

## 📱 페이지별 상세 평가
### 홈페이지
- **보이는 것:** 히어로, 검색, 카테고리, 핫딜 TOP3, 오늘의 물가, 패션 할인, 마트 세일, 주유소, 커뮤니티. 볼륨은 많습니다 (`packages/website/frontend/src/pages/Home/HomePage.jsx:306-845`).  
- **문제:** 많은데 핵심이 흐립니다. 절약 서비스라면 “무엇을 지금 사야 하는지”가 먼저 나와야 하는데, 섹션 나열형 포털에 가깝습니다.  
- **치명점:** 마트 세일 카드 클릭이 상품 상세로 안 가고 탭 이동만 함 (`HomePage.jsx:740-742`).  
- **데이터 품질:** 홈용 `/api/dashboard`의 `category_summary`가 라이브에서 0원 기본값이라 “오늘의 물가”가 무의미했습니다.  
- **평가:** 보기엔 번듯하지만, 첫 30초 안에 “절약 결론”을 주지 못합니다.

### 마트 할인
- **장점:** 상세 모달 자체는 홈보다 낫고, 전단 뷰어/비교 모드/UI 완성도는 나쁘지 않습니다 (`packages/website/frontend/src/pages/Mart/MartPage.jsx:345-549`, `737-829`).  
- **문제:** 비교 기준이 상품 정규화가 아니라 문자열 유사도 수준이라 실제 장보기 비교에 약합니다 (`MartPage.jsx:61-91`).  
- **시세 대비:** 구현은 되어 있지만(`MartPage.jsx:597-612`, `797-803`), 백엔드 기준가 연결이 약해서 “이 수치가 왜 맞는지” 설명력이 떨어집니다.  
- **삼겹살 이슈:** 단순 display bug라기보다 **데이터 정규화 문제**입니다. 라이브 기준 `삼겹살` 대표 상품은 홈플러스·롯데마트 가격이 있는데, 카테고리 비교는 1개 상품만 내려옵니다. 사용자 관점에서는 “마트별 비교가 안 된다”가 체감입니다.

### 물가 비교
- **장점:** 개별 상품 상세 화면 자체는 가장 서비스다운 화면입니다. 현재가/평균/최저/최고/마트별 바차트가 있습니다 (`packages/website/frontend/src/pages/Price/PricePage.jsx:480-718`).  
- **문제:** 카테고리 비교 데이터가 빈약하면 이 장점이 바로 무너집니다.  
- **실사용성:** “삼겹살 전체 마트 비교”를 기대하면 실망합니다. 라이브 `meat.pork.belly` 비교는 1개 상품뿐이고 100g 정규화 값도 null입니다.  
- **한줄 평가:** 개별 상품 카드형 분석은 괜찮지만, 비교 서비스의 본질인 “같은 품목 여러 선택지 비교”는 아직 약합니다.

### 핫딜
- **장점:** 필터/정렬/상세 모달/댓글 UI는 갖춰져 있습니다 (`packages/website/frontend/src/pages/Hotdeal/HotdealPage.jsx:188-301`, `306-501`).  
- **문제:** 현재 라이브 데이터가 너무 약합니다. `test item`, 14일 전, 원가 null, 댓글 0, 조회 0이 많아 ‘지금 볼 가치 있는 딜’처럼 안 보입니다.  
- **투표/댓글 신뢰:** 로그인 기반이 아니라 커뮤니티 검증 배지를 믿기 어렵습니다.  
- **한줄 평가:** 껍데기는 핫딜 서비스인데, 내용은 아직 QA 데이터 느낌입니다.

### 커뮤니티
- **장점:** 목록/상세/댓글/투표/수정/삭제까지 화면 흐름은 있습니다 (`packages/website/frontend/src/pages/Community/CommunityPage.jsx:541-873`).  
- **문제 1:** 상품 태깅 UI는 있지만 저장이 안 됩니다.  
- **문제 2:** 비로그인 글쓰기 UX가 기만적입니다.  
- **문제 3:** 라이브 게시글 데이터에 테스트 흔적이 많아 사용자 신뢰를 해칩니다.  
- **한줄 평가:** 커뮤니티라는 틀은 있는데, 실제 운영 UX로 보기엔 아직 거칠고 헛손질이 많습니다.

### 검색
- **장점:** 자동완성 자체는 여러 곳에서 재사용되고 구현도 깔끔합니다 (`packages/website/frontend/src/components/search/SearchAutocomplete.jsx:99-205`, `329-462`).  
- **문제:** 결과 의미론이 약합니다.  
  - 삼겹살 검색 시 앞다리가 동의어 추천으로 섞임.  
  - `mart` 결과를 `동네` 탭에 넣어 IA가 혼란스러움.  
  - 상품 결과는 종종 모달로만 열려 한 번 더 눌러야 함.  
- **한줄 평가:** “검색은 된다.” 하지만 “정확히 원하는 절약 행동으로 연결된다.”는 아닙니다.

### 주유소/식당
- **주유소:** 리스트·상세는 그럴듯하지만, 실시간 Opinet 체감보다 시드 데이터 재생산 느낌이 강합니다.  
- **식당/배달:** 네이버 장소 상세는 실데이터 기반이지만, `RestDetailContent`는 목업이고 실제로도 거의 쓰이지 않습니다.  
- **반경 필터:** UI만 있고 실제 반영 안 됨.  
- **한줄 평가:** 지역 탐색 데모는 되지만, “동네 절약 지도”로 믿고 쓰기엔 아직 프로토타입입니다.

### 장바구니/찜
- **장바구니:** 정보 부족, 링크 없음, 비교 없음, 전용 페이지 없음.  
- **찜:** 로컬에 저장만 되고 접근 UI가 사실상 없습니다.  
- **한줄 평가:** 저장은 되는데 관리가 안 됩니다. 절약 서비스에서 가장 아쉬운 개인화 영역입니다.

### 회원 기능
- **로그인/회원가입:** 모달 UX는 무난합니다 (`packages/website/frontend/src/components/modals/LoginModal.jsx:20-199`).  
- **문제:** 로그인 후 얻는 가치가 작습니다. 프로필/찜/알림/설정이 준비 중이거나 없음.  
- **추가 문제:** 프론트에는 `updateProfile` 서비스가 있지만, 백엔드엔 `PUT /api/auth/me`가 없습니다 (`packages/website/frontend/src/services/authService.js:35-37`, `packages/website/backend/api/routes/auth.py:261-277`).  
- **한줄 평가:** 가입은 시키는데, 가입 후 생활 반경에 남을 이유를 약하게 줍니다.

### 전체 네비게이션
- **데스크톱:** 상단 메뉴는 이해 가능합니다 (`packages/website/frontend/src/components/layout/Header.jsx:9-16`).  
- **모바일:** 하단 탭은 핵심 기능인 물가비교가 빠져 있습니다 (`packages/website/frontend/src/components/layout/BottomNav.jsx:5-11`).  
- **3클릭 원칙:** 홈→마트상품상세 실패, 홈→주유소상세 실패, 프로필 메뉴→찜/알림/프로필 실패.  
- **한줄 평가:** 큰 메뉴는 보이는데, 핵심 상세 행동으로 내려가는 마지막 1클릭이 자주 빠져 있습니다.

## 📊 기능별 유용성 점수
| Feature | 구현도 | 유용성 | 사용편의 | 정보충분 | 종합 |
|---|---:|---:|---:|---:|---:|
| 홈페이지 | 6 | 3 | 4 | 3 | 4.0 |
| 마트 할인 | 6 | 5 | 5 | 5 | 5.3 |
| 물가 비교 | 7 | 5 | 6 | 5 | 5.8 |
| 핫딜 | 6 | 2 | 5 | 2 | 3.8 |
| 커뮤니티 | 6 | 3 | 4 | 3 | 4.0 |
| 검색 | 7 | 5 | 6 | 4 | 5.5 |
| 주유소/식당 | 5 | 3 | 4 | 3 | 3.8 |
| 장바구니 | 3 | 3 | 5 | 2 | 3.3 |
| 찜/알림 | 2 | 2 | 2 | 1 | 1.8 |
| 회원 기능 | 5 | 3 | 5 | 3 | 4.0 |
| 전체 네비게이션 | 6 | 4 | 4 | 4 | 4.5 |

## 📋 우선순위 개선 목록
### P0
1. 홈 마트 세일 카드 클릭 시 **선택한 상품 상세**를 바로 열 것 (`HomePage.jsx:740-742` → `MartPage.jsx:737-829` 수준으로 연결).
2. 홈 `오늘의 물가`에 **기본값/0원/`etc`** 노출 금지. `/api/dashboard`와 `/api/products/category-summary` 응답 규격부터 맞출 것.
3. 장바구니를 **전용 페이지 또는 상세 연결 가능한 리스트**로 승격하고, 이미지/매장/원문/비교가를 저장할 것.
4. 찜 목록·가격 알림·알림 센터를 **placeholder가 아닌 실제 화면**으로 열 것.
5. 커뮤니티 글쓰기에서 `product_ids`, `tags`를 실제 저장하도록 프론트 payload 수정.
6. 비로그인 글쓰기/투표/댓글 흐름을 **즉시 로그인 유도**로 통일.
7. 테스트용 핫딜/커뮤니티 데이터 제거. 운영 DB와 테스트 데이터 격리.

### P1
1. 삼겹살 같은 핵심 품목의 **카테고리 정규화/단위 정규화**를 손봐서 마트 간 비교가 진짜 되게 만들 것.
2. 모바일 하단 탭에 `물가비교`를 추가하거나, 최소한 검색보다 더 빠른 진입 경로를 줄 것.
3. 지역 페이지 반경 필터를 실제 API 쿼리에 반영할 것.
4. 주유소/지역 데이터에 **수집 시각·출처(Opinet/Naver/시드)**를 명시할 것.
5. 핫딜 상세의 관련 상품/시세 비교를 클릭 가능하게 만들 것.

### P2
1. 홈을 섹션 포털이 아니라 **“오늘 절약 행동 추천” 대시보드**로 재편.
2. 장보기 리스트에 **최저가 기준 자동 재정렬/대체상품 추천** 추가.
3. 검색 결과 타입 라벨 정리 (`mart`를 `동네`로 부르지 말 것).
4. 에러/빈 상태를 “왜 비었는지 + 다음 행동” 중심으로 개선.
5. 프로필 수정 흐름(프론트/백엔드) 실제 구현.
