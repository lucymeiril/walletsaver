# WalletSavior 2차 프로젝트 분석 보고서
## GPT-5.4 심층 분석

### 전체 요약
이 프로젝트는 **완전한 목업은 아니고 실제 DB/가격 이력/커뮤니티 CRUD가 돌아가는 데모형 서비스**입니다. 다만 2차 점검 기준으로 보면, 핵심 가치인 **"가격 비교"와 "오늘의 물가"의 데이터 무결성**이 아직 약합니다.

좋아진 점도 분명합니다. 1차 지적 이후:
- `packages\crawler-admin\backend\pipeline\pipeline.py`의 기본 ingestion URL은 `8002`로 수정됨
- `packages\db-admin\backend\config.py`의 `REQUIRE_AUTH` 기본값이 `true`로 바뀜
- OAuth 콜백은 URL 토큰 전달 대신 쿠키 기반으로 정리됨
- 현재 `crawler-admin` 백엔드 테스트는 **344 passed, 20 skipped**로 통과함

하지만 더 깊게 보면 다음이 남아 있습니다.
- **오늘의 물가 API가 실제 카테고리 비교를 하지 못함** (`/api/products/category-summary`가 사실상 `etc` 1개로 붕괴)
- **카테고리 비교 기능이 데이터/계약 양쪽에서 깨져 있음**
- **크롤러 코드는 대체로 실제 구현이지만, 안전한 인증이 켜진 운영 구성을 기준으로는 DB 적재 경로가 미완성**
- **website ↔ db-admin 결합이 여전히 강함** (`sys.path` + 동일 SQLite 직접 공유)
- **실사용 데이터와 테스트/시드 데이터가 섞여 있어 사용자 경험이 데모 성격을 벗어나지 못함**

현재 상태를 한 줄로 요약하면: **“보여줄 것은 있는 데모”지만, “데이터를 믿고 쓰는 생활 서비스” 단계는 아직 아닙니다.**

### 📊 데이터 흐름 분석
#### 1) 크롤링 → 파이프라인 → DB 적재
흐름 자체는 존재합니다.
- 크롤러 실행: `packages\crawler-admin\backend\crawlers\**\crawler.py`
- 검증/정제/변환: `packages\crawler-admin\backend\pipeline\pipeline.py`, `validator.py`, `transformer.py`
- 리뷰 큐 적재: `packages\db-admin\backend\api\routes\ingestion.py`
- 최종 DB 삽입: `packages\db-admin\backend\api\routes\ingestion.py:_insert_items`

파이프라인 로직은 실제로 다음 단계를 밟습니다.
1. 크롤러 실행
2. 필수 필드 검증 / 가격 정규화 / 중복 제거
3. 카테고리 enrich
4. `DiscountItem` / `HotdealPost`를 DB 적재용 dict로 변환
5. 리뷰 큐(`pending_ingestions`) 또는 bulk 저장 API로 전송

즉, **코드는 end-to-end를 지향**합니다.

#### 2) 그런데 실제 데이터 무결성은 중간에서 깨집니다
현재 DB 실데이터를 보면:
- `products`: **1171건**
- `baseline_prices`: **1488건**
- `discount_history`: **1638건**
- `hotdeal_prices`: **20건**
- `posts`: **217건**
- `pending_ingestions`: **17건**
- `crawl_logs`: **0건**
- `delivery_items`: **0건**
- `shopping_items`: **0건**

문제는 **양보다 연결성**입니다.

##### A. website는 db-admin API를 소비하는 구조가 아니라 DB를 직접 읽습니다
- `packages\website\backend\api\app.py:130-153`
- `packages\website\backend\services\db.py:19-26`

즉 데이터 흐름이 문서상 서비스 연동이 아니라 실제로는:

`crawler/admin/db-admin이 만든 walletguardian.db` → `website backend가 같은 파일을 직접 열어서 조회`

입니다.

##### B. `오늘의 물가`는 실제 비교 데이터가 아니라 잘못 집계됩니다
- API: `packages\website\backend\api\routes\products.py:150-239`
- 원천 조회: `storage.search_products()` 결과 사용
- 하지만 `search_products()`가 반환하는 key는 `cat`, `cur` 중심이고, `category_id`/`category`를 주지 않음 (`packages\db-admin\backend\storage\db.py:600-625`)
- 반면 `category-summary`는 `p.get("category_id") or p.get("category")`로 그룹핑함 (`products.py:203-206`)

실제 확인 결과 `/api/products/category-summary` 응답은 다음처럼 나옵니다.
- `category_id: "etc"`
- count 33
- 카테고리 하나만 반환

즉 **“오늘의 물가”가 카테고리별 물가 요약이 아니라 사실상 한 바구니 합산값**입니다.

##### C. 카테고리 비교는 데이터가 있어도 쓸 수 없는 상태입니다
- API: `packages\db-admin\backend\storage\db.py:1426-1581`
- 이 기능은 `Product.attributes.weight_g`, `storage`, `origin`, `usage`를 전제로 `per_100g`를 계산함

그런데 실제 DB 상태는:
- `category_id`가 있는 상품: **24/1171건**
- `attributes`가 채워진 상품: **0/1171건**

실제 `vegetable.root.onion` 비교 결과도:
- `avg_per_100g = null`
- `min_per_100g = null`
- `max_per_100g = null`
- `per_100g = null`

즉 UI에선 “100g당 비교”를 말하지만, **정규화 가격을 계산할 데이터가 없습니다.**

##### D. 핫딜은 보이지만 비교 데이터로는 약합니다
`hotdeal_prices`는 20건뿐이고, 응답도 대부분 아래 상태입니다.
- `origPrice: null`
- `thumb: null`
- `views: 0`
- `comments: 0`
- `is_verified: false`
- 최신 데이터도 감사 시점 기준 **13일 전**

원인은 스키마 자체에 있습니다.
- `packages\db-admin\backend\storage\models.py:234-257`

`HotdealPrice`는 `price`, `source`, `title`, `votes_hot/not`, `is_verified` 정도만 저장합니다. **원가, 배송비, 썸네일, 댓글수, 조회수, 판매처 구조화 필드가 없습니다.** 그래서 프론트는 진짜 핫딜 분석이 아니라 “제목+가격 목록” 수준에서 멈춥니다.

##### E. 커뮤니티의 적정가 제안은 로직은 있으나 연결이 없습니다
- 로직: `packages\website\backend\api\routes\community.py:407-467`
- 하지만 실제 DB에서 `posts.product_id is not null` 건수는 **0건**

원인은 프론트 작성 payload입니다.
- `packages\website\frontend\src\pages\Community\CommunityPage.jsx:232-240`
- 스키마는 `product_ids`, `tags`를 받을 수 있는데 (`api\schemas\community.py:14-25`), 프론트는 선택한 상품을 거의 보내지 않습니다.

결과적으로 **적정가 제안은 “실제 가격 데이터 기반 기능”처럼 보이지만, 현재 운영 데이터에선 대부분 `unknown`으로 끝날 가능성이 높습니다.**

### 🕷️ 크롤러 실태 분석
#### 총평
2차 검토에서 확인한 결론은 명확합니다.

**크롤러들은 “대부분 실제 구현”입니다.** 1차 보고서 시점과 달리 현재는 `crawler-admin` 테스트도 통과합니다.
- 실행 결과: **344 passed, 20 skipped, 86 warnings**

즉, 이 영역은 “전부 스켈레톤”이 아니라 **구현은 꽤 되어 있고, 사이트별 현실적 한계가 섞여 있는 상태**입니다.

#### 1) 실제로 구현된 크롤러
실제 requests/BeautifulSoup/Playwright/재시도 로직이 있는 크롤러들:
- 핫딜: `ppomppu`, `fmkorea`, `clien`, `algumon`, `quasarzone`, `arca`
- 마트: `emart`, `homeplus`, `lottemart`, `cocodalin`
- 쇼핑: `musinsa`, `uniqlo`, `giordano`
- 공공: `opinet`
- 위치: `naver_place`
- 배달: `baemin`, `yogiyo`, `coupangeats`

대표 근거:
- `packages\crawler-admin\backend\crawlers\marts\emart\crawler.py`
- `packages\crawler-admin\backend\crawlers\hotdeals\ppomppu\crawler.py`
- `packages\crawler-admin\backend\crawlers\government\opinet\crawler.py`

#### 2) 실제성/현실성 평가
##### 실사용 가능성이 높은 편
- `opinet`: 공공 API + fallback 구조라 가장 현실적
- `ppomppu`, `fmkorea`, `clien`, `quasarzone`: HTML 기반 커뮤니티 크롤러라 비교적 현실적
- `emart`: `__NEXT_DATA__` 파싱 기반이라 구현 완성도 높음
- `cocodalin`: 코스트코 할인 API 직접 호출 구조

##### 부분 구현 또는 환경 의존이 강함
- `homeplus`, `musinsa`, `uniqlo`, `naver_place`: Playwright 의존도가 높음
- `baemin`, `yogiyo`, `coupangeats`: 코드 자체는 있으나, 서비스 구조상 주소 설정/인증/앱 전용 제한이 강함

즉 **코드는 있어도 “오늘 당장 안정적으로 계속 돌릴 수 있는가”는 별개**입니다.

#### 3) 명시적으로 비활성/불능인 크롤러
- `packages\crawler-admin\backend\crawlers\hotdeals\cocodal\crawler.py`

여기는 파일 주석과 구현 모두에서 **사이트 접속 불가로 즉시 FAILED 반환**합니다. 이건 스켈레톤이라기보다 **의도적으로 죽여둔 크롤러**입니다.

#### 4) 안티봇/레이트리밋 대응
장점:
- `packages\crawler-admin\backend\engine\anti_detect.py`
- User-Agent rotation, Accept 헤더 variation, proxy rotation, random delay 구현
- 각 크롤러에도 429/backoff 재시도 로직이 꽤 반복적으로 들어가 있음

한계:
- 많은 크롤러가 async 흐름 안에서 `time.sleep()`를 사용함 → 이벤트루프 블로킹 위험
- Playwright/helper 미설치 환경에서는 fallback 품질이 크게 떨어짐
- 배달앱 계열은 코드가 있어도 **서비스 정책상 사실상 수집 한계**가 명시됨

#### 5) 파이프라인 → DB 전송의 운영상 빈틈
- `packages\crawler-admin\backend\pipeline\pipeline.py:295-360`

여기서 ingestion API 호출 시 **인증 헤더를 넣지 않습니다.**
즉 `db-admin`이 기본 설정대로 `REQUIRE_AUTH=true`이면, 운영 환경에선 이 경로가 바로 막힐 수 있습니다.

현재 DB의 `pending_ingestions` 17건은 전부 `PENDING`이고, 최근 항목 이름도 `test_auth`라서 **실크롤 결과보다는 테스트 흔적이 섞여 있음**이 보입니다.

결론적으로:
- **크롤러 구현 자체는 생각보다 진짜다**
- 그러나 **운영형 데이터 파이프라인으로 닫히는 증거는 아직 약하다**

### 🗄️ 데이터베이스 설계 평가
#### 장점
- 가격 계층이 분리되어 있음
  - `baseline_prices`
  - `discount_history`
  - `hotdeal_prices`
- 커뮤니티 테이블이 분리되어 있음
  - `posts`, `comments`, `votes`, `post_images`
- 리뷰 큐/품질관리 테이블이 있음
  - `pending_ingestions`, `pending_categorizations`, `category_corrections`, `audit_logs`
- 인덱스도 기본적인 시간축/상품축 위주로는 꽤 들어가 있음

#### 1) 기능 대비 스키마 공백
##### A. 핫딜 기능에 필요한 필드가 부족함
`HotdealPrice`에는 아래가 없습니다.
- 원가
- 배송비
- 판매처 구조화
- 썸네일
- 조회수/댓글수 원본
- 카테고리 정규화 필드

그래서 UI가 “핫딜 평가/비교”를 해도 실제론 **제목 문자열 파싱 + 현재가** 중심입니다.

##### B. 카테고리 비교에 필요한 정규화 필드가 비어 있음
카테고리 비교 API는 `attributes.weight_g`, `storage`, `origin`, `usage`를 가정하지만, 실제 DB에는 **attributes가 채워진 상품이 0건**입니다.

즉 설계상 존재하는 기능이 **실데이터 스키마 활용까지 닫히지 못했습니다.**

##### C. 사용자 설정/알림/모더레이션 스키마가 부족함
있는 것:
- `favorites`
- `price_alerts`

없는 것:
- `user_settings` / `preferences`
- 일반 알림 테이블 (`notifications`)
- 신고 내역 테이블
- 관리자 모더레이션 큐
- 차단/제재 이력

즉 **“알림/설정/운영” 축은 거의 비어 있습니다.**

#### 2) Product 마스터 오염 문제
`packages\db-admin\backend\api\routes\ingestion.py:_ensure_product()`는 매칭 실패 시 새 상품을 바로 생성합니다.
- unit 기본값: `"개"`
- source_type: crawler source 기반 또는 `unknown`
- 이름: 크롤 원문 제목 그대로 들어갈 수 있음

실제 DB 상위 중복/원시 제목 예시:
- `양파` 2건
- `(DEFG X US) SLEEVE LOGO T-SHIRTS [3COLOR]`
- `[농할 20%쿠폰 상세 다운] 수제망 양파 ...`

즉 Product가 **정규화된 품목 마스터**이기도 하고, 동시에 **크롤링된 원문 상품 레코드 저장소**처럼 쓰입니다. 이 상태에선 비교/분류 품질이 계속 흔들립니다.

#### 3) 마이그레이션 전략은 “있지만 일관되게 쓰지 않음”
Alembic은 존재합니다.
- `packages\db-admin\backend\storage\migrations\versions\8018226a8e9e_initial_complete_schema.py`

하지만 동시에:
- `packages\db-admin\backend\storage\db.py:107-110` → `Base.metadata.create_all()`
- `packages\website\backend\api\routes\community.py:52-63` → `create_all()` + `ALTER TABLE tags` 실행

즉 현재는 **마이그레이션 도구가 있음에도 런타임 코드가 스키마를 직접 건드리는 혼합 방식**입니다. 운영 환경에서 스키마 drift를 부르기 쉽습니다.

### 👤 실사용자 관점 평가
#### 실제 한국 사용자가 오늘 들어오면 보게 될 것
##### 1) 오늘의 물가
겉으로는 카드가 보이겠지만, 실제 API 응답은 아래처럼 나옵니다.
- 카테고리 1개: `etc`
- 평균가 23113원
- 최저/최고/단위도 뒤섞임

즉 사용자는 **“축산물/채소/과일 물가를 본다”가 아니라 정체불명의 `etc` 요약**을 보게 됩니다.
이건 현재 사이트에서 가장 큰 체감 결함 중 하나입니다.

##### 2) 검색
검색은 동작합니다. `/api/search?q=양파`도 결과를 돌려줍니다.
하지만 품질은 섞여 있습니다.
- 정상 품목: `양파`
- 원문 크롤 제목 그대로인 상품들
- `mart` 결과는 일부 `price: null`
- 핫딜 결과는 오래되고 메타데이터가 빈약함

즉 **“안 나오지는 않지만, 신뢰도 높은 생활 검색” 수준은 아닙니다.**

##### 3) 가격 비교
- 개별 품목 상세/가격 이력은 일부 핵심 품목(양파, 삼겹살, 계란 등)에서 비교적 그럴듯하게 동작
- 그러나 **카테고리 비교는 실질적으로 실패 상태**
  - 100g 정규화 불가
  - 필터(storage/origin/usage) 작동 불가
  - 프론트가 기대하는 summary key와 백엔드 응답 key도 다름

##### 4) 커뮤니티
기능 자체는 돌아갑니다.
- 글 작성
- 댓글 작성
- 투표
- 수정/삭제

테스트도 이를 보여줍니다.

하지만 실운영 관점에서는 문제가 있습니다.
- DB의 최신 글 상당수가 테스트 제목
- `product_id` 연결이 0건이라 가격 검증/적정가 제안이 약함
- 운영자용 신고/모더레이션 도구가 없음

즉 **커뮤니티는 기능은 있지만 운영 준비는 안 된 상태**입니다.

##### 5) 동네/생활 정보
- 주유소: 8건
- 식당: 3건

응답 자체는 오지만 이름이 `맛있는 한식당`, `중화반점`, `스시오마카세`처럼 **데모성 데이터**에 가깝습니다. 실제 한국 사용자 입장에서는 “실시간 동네 정보 서비스”로 보기 어렵습니다.

### ⚡ 성능 및 확장성
#### 1) N+1 / 쿼리 비효율
##### 커뮤니티 목록
- `packages\website\backend\api\routes\community.py:72-96, 145-176`
- `_post_to_dict()`에서 `post.votes`, `post.comments`, `post.author`, `post.images`를 순회
- eager loading이 없어 목록 1페이지당 추가 쿼리가 쉽게 늘어남

##### 상품 검색
- `packages\db-admin\backend\storage\db.py:542-625`
- 각 상품마다 `_compute_product_stats()`, `_get_store_prices()`, 최신 discount 조회를 반복
- 현재 데이터 양에서는 버티지만, 상품 수가 더 늘면 페이지 응답이 무거워질 가능성 큼

##### 식당 주변 검색
- `packages\website\backend\api\routes\restaurants.py:46-83`
- DB에서 최대 1000건을 메모리로 읽은 뒤 haversine 계산/정렬
- 지금은 3건이라 티가 안 나지만, 데이터가 늘면 바로 비효율화

#### 2) 인덱스는 기본은 괜찮지만, 기능과 데이터 품질이 더 큰 병목
지금은 “인덱스 부족”보다도,
- category_id 없는 상품 다수
- attributes 비어 있음
- source_type `unknown` 624건

같은 **데이터 정규화 실패**가 더 큰 성능/정확도 병목입니다.

#### 3) 캐싱은 있으나 운영형은 아님
- TTLCache가 여러 군데 잘 들어가 있음
- 하지만 rate limit/storage 기본값이 `memory://`라 다중 프로세스/다중 인스턴스에선 무력화
- hotdeal vote/report도 인메모리 dict 기반 (`packages\website\backend\api\routes\hotdeals.py:29-45`)

#### 4) 장애 은닉 문제
- `StorageProxy`는 DB 실패 시 circuit breaker를 열고 빈 배열/기본값으로 흘리기 쉬움
- 여러 API가 `except Exception` 후 빈 데이터로 복구

사용자는 “서버 장애”를 보기보다 “데이터가 없는 서비스”처럼 보게 됩니다.

### 🔗 통합 및 결합도
#### 1) website ↔ db-admin 결합은 여전히 남아 있습니다
- `packages\website\backend\services\db.py`
- `packages\website\backend\api\app.py`

여전히:
- `sys.path` 삽입
- `storage.models`, `storage.db` 직접 import
- db-admin의 SQLite 파일 직접 사용

즉 **서비스 분리가 아니라 모놀리식 DB 공유 구조**입니다.

#### 2) crawler → db-admin 파이프라인은 코드상 연결되지만, 보안 설정을 켜면 미완성입니다
- `pipeline.py`는 ingestion API를 호출함
- 하지만 서비스 인증 헤더를 붙이지 않음
- `db-admin`은 기본적으로 auth가 켜짐

그래서 **“개발 편의 모드”에서는 흘러갈 수 있어도, 정상 보안 설정의 운영형 통합은 아직 덜 끝났습니다.**

#### 3) 프론트 ↔ 백엔드 계약 불일치가 일부 남아 있습니다
가장 큰 사례:
- 프론트 `CategoryComparePage`는 `summary.avg_price_per_100g`, `hotdeal_threshold`, `pagination`, `alternatives`를 기대
- 백엔드는 `avg_per_100g`만 주고 threshold/alternatives/pagination object를 주지 않음
- 파일:
  - `packages\website\frontend\src\pages\Price\CategoryComparePage.jsx`
  - `packages\db-admin\backend\storage\db.py:1426-1581`

즉 **HTTP 200은 나오지만 UX는 깨진 계약**입니다.

### 🚫 부재 기능
현재 있어야 하는데 없는 것들:

1. **공개 엔드포인트 전반의 일관된 rate limit**
   - search/auth 일부만 적용
   - hotdeals/products/list 계열은 사실상 느슨함

2. **분산 캐시 / 분산 rate limit**
   - Redis 기반 운영 전략 부재

3. **에러 모니터링 / 알림**
   - Sentry, OpenTelemetry, Prometheus 류 부재

4. **사용자 설정/환경설정 저장**
   - 가격 알림만 있고 일반 `settings/preferences` 없음

5. **일반 알림 시스템**
   - `price_alerts` 외 푸시/인앱/이벤트 알림 없음

6. **콘텐츠 모더레이션 툴**
   - 신고 접수 후 처리하는 운영 UI/API 없음
   - 신고 저장 자체도 빈약함

7. **실제 운영용 크롤링 관제 지표**
   - `crawl_logs`가 0건
   - 최근 성공/실패/지연 추적이 빈약

8. **delivery/shopping 실데이터 적재 완결성**
   - `delivery_items = 0`
   - `shopping_items = 0`

### 🧪 테스트 신뢰도
#### 이번 점검에서 직접 실행한 테스트
- `db-admin backend`: **307 passed, 563 warnings**
- `website backend`: **201 passed, 1 failed**
  - 실패: `tests/test_api_routes.py::TestProducts::test_price_history`
- `crawler-admin backend`: **344 passed, 20 skipped, 86 warnings**

즉 1차 보고서 때와 달리 **crawler-admin 테스트 상태는 개선**됐습니다.

#### 하지만 테스트가 놓치는 핵심 경로
##### 1) 의미 검증보다 상태코드 검증이 많음
- `packages\integration-tests\test_api_contracts.py`
- 응답 envelope, status code, pagination key 유무 검증이 중심

그래서 `/api/products/category-summary`가 실제로 `etc` 1개만 줘도 **테스트는 통과할 수 있습니다.**

##### 2) e2e 테스트가 실제 운영 DB를 오염시킴
- 최신 `posts`를 보면 `흐름 테스트`, `투표 토글 테스트`, `삭제 테스트` 같은 제목이 다수
- 즉 테스트가 공유 DB를 사용하며, 감사 시점의 실제 데이터 품질도 흐립니다

##### 3) 프론트엔드 페이지 테스트 공백
현재 프론트 테스트는 공통 컴포넌트/훅/플러그인 쪽이 중심이고,
- 홈
- 가격 비교 페이지
- 커뮤니티 페이지
- 로컬 페이지
같은 핵심 사용자 플로우 페이지 검증은 매우 약합니다.

##### 4) 없는 테스트
- `category-summary`가 여러 실카테고리를 반환하는지
- category compare가 실제 `per_100g` 값을 만들 수 있는지
- hotdeal/community 작성 시 `product_ids`가 실제 저장되는지
- crawler → db-admin ingestion이 `REQUIRE_AUTH=true`에서도 통과하는지
- 실데이터와 테스트데이터가 분리되는지

### 📈 진척도 평가
| Feature | 계획 | 구현 | 동작 | 비고 |
|---|---|---|---|---|
| 개별 품목 가격 조회/이력 | 있음 | 있음 | 부분 성공 | 핵심 품목은 동작하지만 테스트 1건 실패 존재 |
| 오늘의 물가 요약 | 있음 | 있음 | 실패에 가까운 부분 동작 | 실제 응답이 `etc` 1개로 붕괴 |
| 카테고리 가격 비교 | 있음 | 있음 | 부분 실패 | `per_100g`가 대부분 `null`, 프론트/백엔드 계약도 불일치 |
| 핫딜 크롤링/목록 | 있음 | 있음 | 부분 동작 | 데이터 20건뿐, 메타데이터 빈약, 최신성 낮음 |
| 핫딜 투표/댓글 | 있음 | 있음 | 동작 | 영속화는 되나 운영 정책/모더레이션 부족 |
| 커뮤니티 게시판 | 있음 | 있음 | 동작 | CRUD/댓글/투표 가능, 다만 테스트 데이터 오염 심함 |
| 커뮤니티 적정가 제안 | 있음 | 있음 | 사실상 미동작 | `posts.product_id`가 0건이라 실사용성이 낮음 |
| 통합 검색 | 있음 | 있음 | 부분 동작 | 검색은 되지만 결과 품질이 원문 title/price null 등으로 혼재 |
| 주유소/식당 로컬 정보 | 있음 | 있음 | 데모 수준 동작 | gas 8건, restaurants 3건, 시드/샘플성 강함 |
| 배달앱 가격 비교 | 있음 | 부분 구현 | 미완성 | delivery 테이블 0건, 앱 인증/주소 의존성 큼 |
| 패션/쇼핑 크롤링 | 있음 | 부분 구현 | 불확실 | 크롤러 코드는 있으나 shopping_items 적재 0건 |
| 크롤러 승인 파이프라인 | 있음 | 있음 | 부분 동작 | 리뷰 큐 구조는 좋지만 운영 인증 경로가 미완성 |
| 사용자 프로필/즐겨찾기/가격알림 | 있음 | 있음 | 동작 | 일반 settings/notifications는 없음 |
| 사용자 설정/환경설정 | 있어야 함 | 거의 없음 | 미구현 | 별도 settings/preferences persistence 없음 |
| 일반 알림/공지 | 있어야 함 | 거의 없음 | 미구현 | price alert 외 알림 체계 없음 |
| 운영자 모더레이션 툴 | 있어야 함 | 거의 없음 | 미구현 | 신고 처리/제재/검토 UI/API 부재 |
| 마이그레이션/스키마 운영 | 있음 | 혼합 | 불안정 | Alembic 존재 + runtime `create_all` 혼용 |

### 📋 우선순위별 액션 아이템
#### P0 (출시 차단)
1. **`/api/products/category-summary`를 즉시 고치기**
   - `search_products()` 결과 shape와 집계 로직 key를 맞춰서 실제 카테고리별 요약이 나오게 해야 함
2. **카테고리 비교 기능을 데이터 기준으로 다시 닫기**
   - `category_id`, `attributes.weight_g/storage/origin/usage`를 실제 적재하도록 파이프라인/분류기를 연결
   - 아니면 기능 범위를 축소하고 UI도 단순화
3. **community hotdeal 작성 시 `product_ids` 저장 경로 복구**
   - 프론트 payload와 백엔드 스키마를 맞춰 `posts.product_id`가 실제 채워지게 해야 함
4. **crawler → db-admin 인증 경로 완성**
   - service API key/JWT를 파이프라인에서 붙이도록 수정
   - `REQUIRE_AUTH=true` 상태의 실제 e2e 테스트 추가
5. **website의 db-admin 직접 결합 해소 계획 수립**
   - 최소한 `sys.path` + 동일 SQLite 직접 공유는 벗어나야 함

#### P1 (중요)
1. **Product 마스터 정규화**
   - 원문 title과 비교용 품목 마스터를 분리
   - 중복/오염 상품 정리
2. **핫딜 스키마 강화**
   - 원가, 썸네일, 판매처, 배송비, 카테고리, 최신성 메타데이터 저장
3. **커뮤니티/검색의 의미 기반 테스트 추가**
   - “결과가 나온다”가 아니라 “의미 있는 결과가 나온다”를 검증
4. **N+1 정리**
   - community 목록 eager loading
   - product search/stats 조회 최적화
5. **테스트 DB 분리**
   - e2e 테스트가 운영/공유 SQLite를 오염시키지 않도록 격리

#### P2 (개선)
1. **Redis 기반 rate limit/cache 도입**
2. **Sentry/메트릭/알림 체계 도입**
3. **restaurants/gas가 데모 데이터면 UI에 명시** 또는 실제 데이터 수집 연동
4. **Alembic만 쓰도록 스키마 관리 일원화**
5. **프론트엔드 핵심 페이지 테스트 확대**

