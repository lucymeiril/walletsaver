# WalletSavior 프로젝트 비평 보고서
## 작성 기준: GPT-5.4 코드 리뷰

### 요약
이 프로젝트는 “졸업작품 데모”로는 볼거리가 있지만, “구조가 잘 분리된 서비스”라고 부르기엔 과장이 많습니다. 특히 **website ↔ db-admin 직접 결합**, **OAuth/JWT 보안 설계 미흡**, **플러그인 시스템의 이중 구조**, **문서-구현 불일치**, **테스트의 신뢰도 부족**이 큽니다.  
실행 검증 결과도 좋지 않습니다. **website backend pytest는 즉시 깨졌고**, **crawler-admin pytest는 hang**, **db-admin만 비교적 안정적**이었습니다. 프론트 빌드는 되지만, “빌드됨”과 “완성도 높음”은 전혀 다른 이야기입니다.

### 🔴 심각 (즉시 수정 필요)
1. **website backend가 현재 테스트 컨텍스트에서 바로 깨집니다.**  
   - `packages/website/backend/api/app.py:100-105`  
   - `error_middleware`, `error_api`를 import하지만 실제 파일은 `packages/shared/`에 있고 경로 주입이 없습니다. 실제 `py -m pytest tests -q --tb=short` 실행 시 `ModuleNotFoundError`가 발생했습니다. 기본 앱 팩토리조차 안정적으로 못 띄우는 상태입니다.

2. **서비스 분리가 문서와 다르게 사실상 깨져 있습니다. website backend가 db-admin에 파일 경로로 직결됩니다.**  
   - `docs/API_CONTRACTS.md:5-28`  
   - `packages/website/backend/api/app.py:130-153`  
   - `packages/website/backend/services/db.py:20-26`  
   - `packages/website/backend/.env:4`  
   - 문서는 프로젝트 간 REST 통신을 말하지만, 실제 코드는 `sys.path`를 조작해 db-admin 백엔드의 `storage.db`, `storage.models`를 직접 가져오고, DB도 `packages/db-admin/backend/walletguardian.db`를 공유합니다. 이건 분리가 아니라 **파일시스템 의존 하드커플링**입니다.

3. **OAuth 토큰을 URL 쿼리스트링으로 프론트에 넘깁니다. 보안상 매우 나쁩니다.**  
   - `packages/website/backend/api/routes/auth.py:202-205`  
   - `packages/website/frontend/src/pages/Auth/AuthCallback.jsx:15-28`  
   - 브라우저 히스토리, 리퍼러, 프록시 로그에 토큰이 남습니다. 프론트는 이를 다시 `sessionStorage`에 저장합니다. 현대적인 설계와 거리가 멉니다.

4. **민감정보가 저장소에 커밋돼 있습니다.**  
   - `packages/website/backend/.env:15`  
   - `packages/website/backend/.env:22-23`  
   - JWT 시크릿과 Google OAuth 클라이언트 정보가 그대로 들어 있습니다. `.env.example` 수준이 아니라 실제 값이 저장소에 들어간 건 치명적입니다.

5. **crawler-admin 로그인은 사실상 가짜입니다. 아무 API 키나 저장될 수 있습니다.**  
   - `packages/crawler-admin/frontend/src/stores/authStore.js:15-26`  
   - `packages/crawler-admin/backend/api/security/auth.py:15,47-52`  
   - 프론트는 `/health`에 API 키를 붙여 호출해서 “로그인 성공” 여부를 판단하는데, `/health`는 공개 경로입니다. 즉 **검증되지 않은 임의 문자열도 로그인 상태로 저장**됩니다. UX도 망가지고 보안 모델도 망가집니다.

6. **crawler-admin의 SSE 실시간 상태 스트리밍은 인증 구조상 거의 동작할 수 없습니다.**  
   - `packages/crawler-admin/frontend/src/api/client.js:116-183`  
   - `packages/crawler-admin/backend/api/app.py:110-115`  
   - `packages/crawler-admin/backend/api/security/auth.py:37-77`  
   - SSE는 `EventSource`로 열리는데 커스텀 `X-API-Key` 헤더를 못 보냅니다. 반면 백엔드는 해당 라우터 전체에 API 키 의존성을 걸었습니다. 결과적으로 “실시간 스트리밍 지원”은 코드상 존재해도 구조상 막혀 있습니다.

7. **플러그인 시스템은 ‘있다’기보다 ‘두 벌이 따로 돈다’에 가깝습니다.**  
   - `packages/crawler-admin/backend/api/routes/plugins.py:74-119`  
   - `packages/crawler-admin/backend/plugins/plugin_manager.py:61-192`  
   - `packages/website/frontend/src/App.jsx:87-97`  
   - 백엔드 라우트는 `plugin.yaml`을 직접 스캔하고, 런타임 `PluginManager`는 별도로 존재하지만 둘이 연결되지 않습니다. 게다가 website 프론트에는 Plugin SDK/Marketplace 코드가 대량으로 있으나 App 라우팅에 실제로 붙지 않습니다. **“플러그인 시스템”이 아니라 실험 코드와 운영 코드가 분리된 상태**입니다.

8. **커뮤니티의 suggested-tier 기능은 사실상 죽어 있습니다.**  
   - `packages/website/backend/api/routes/community.py:399-426`  
   - `orig`를 끝까지 `None`으로 두고 계산하므로 실제로는 거의 항상 `unknown`을 반환합니다. 화면에 기능은 있어도 판단 로직은 성립하지 않습니다.

9. **검색/가격 비교 핵심 API가 겉만 그럴듯하고 내부는 허술합니다.**  
   - `packages/website/backend/api/routes/search.py:47-62,77-95,118-123`  
   - `packages/website/backend/api/routes/products.py:76-80`  
   - `packages/website/backend/api/routes/hotdeals.py:67-70`  
   - 검색은 관련도 정렬이 아니라 결과를 그냥 합치고, `popular`는 가격으로 정렬합니다. pagination total도 실제 total이 아니라 추정치입니다. 이건 검색/페이지네이션이 아니라 **대충 모양만 맞춘 API**입니다.

10. **핫딜 엔드포인트는 인증/권한 모델이 허술하고 응답 구조도 뒤죽박죽입니다.**  
   - `packages/website/backend/api/routes/hotdeals.py:119-165`  
   - `packages/website/backend/api/routes/hotdeals.py:168-185`  
   - `packages/website/backend/api/routes/hotdeals.py:225-260`  
   - 핫딜 투표는 인증 없이 IP 기반으로만 처리되고, 댓글도 익명 작성이 가능하며, 신고는 저장 실패해도 성공 응답을 돌립니다. 심지어 `ApiResponse(data={"success": True, ...})` 식으로 **응답 envelope 안에 또 success를 넣는** 비일관성까지 있습니다.

11. **Docker 구성은 현재 저장소와 맞지 않아 바로 실행 불가입니다.**  
   - `docker-compose.yml:37-74`  
   - `docker-compose.dev.yml:8-29`  
   - `./proj`, `./proj/frontend-react`, `./nginx/default.conf`를 참조하지만 현재 저장소 구조와 맞지 않습니다. 배포 문서가 아니라 **고장 난 유물**입니다.

12. **website의 크롤러 실행 API는 명백한 placeholder입니다.**  
   - `packages/website/backend/api/routes/crawlers.py:64-72`  
   - “Phase 2 예정” 메시지와 `# TODO`가 그대로 남아 있습니다. 광고하는 기능 범위와 실제 구현 범위가 다릅니다.

### 🟡 경고 (조속한 수정 권장)
1. **홈페이지는 이미 통합 `/api/dashboard`가 있는데도 여전히 8개 요청을 병렬로 쏩니다.**  
   - `packages/website/backend/api/app.py:286-339`  
   - `packages/website/frontend/src/pages/Home/HomePage.jsx:128-144`  
   - 백엔드는 “8 calls → 1” 최적화를 만들었는데, 프론트가 안 씁니다. 아키텍처 의사결정이 코드에 반영되지 않았습니다.

2. **커뮤니티 목록 정렬 옵션 중 `comments`가 실제로 구현되지 않았습니다.**  
   - `packages/website/backend/api/routes/community.py:158-163`  
   - `comments` 정렬이 `created_at` 정렬과 동일합니다. 옵션만 있고 동작은 같습니다.

3. **website 프론트 서비스 레이어에 죽은 코드와 존재하지 않는 API 계약이 남아 있습니다.**  
   - `packages/website/frontend/src/services/productService.js:28-31` (`/api/products/compare`)  
   - `packages/website/frontend/src/services/hotdealService.js:22-37` (`vote` 필드명 불일치, `POST /api/hotdeals` 없음)  
   - `packages/website/frontend/src/services/authService.js:39-44` (`/api/auth/social/{provider}` 없음)  
   - 실제 백엔드 `packages/website/backend/api/routes/*.py`에는 해당 라우트가 없습니다. 서비스 파일만 남은 **반쪽 구현**입니다.

4. **CategoryComparePage 에러 문구가 잘못됐습니다.**  
   - `packages/website/frontend/src/pages/Price/CategoryComparePage.jsx:382-387`  
   - 에러 상태인데 “불러오는 중입니다”라고 출력합니다. 작은 문구 같지만, 장애 상황 UX를 크게 해칩니다.

5. **CommunityPage는 API 실패 시 별도 에러 상태 없이 토스트만 띄우고, 화면상으로는 ‘빈 목록’처럼 보이기 쉽습니다.**  
   - `packages/website/frontend/src/pages/Community/CommunityPage.jsx:101-114`  
   - `packages/website/frontend/src/pages/Community/CommunityPage.jsx:541-617`  
   - 실패와 진짜 빈 상태를 구분하지 못하는 UX입니다.

6. **Footer와 Header에 placeholder가 남아 있습니다.**  
   - `packages/website/frontend/src/components/layout/Footer.jsx:13-15`  
   - `packages/website/frontend/src/components/layout/Header.jsx:154-161`  
   - 이용약관/개인정보처리방침/문의 링크가 `#`이고, 프로필/찜/알림도 “준비 중” 토스트로 끝납니다. 출시 기준으로는 미완성입니다.

7. **Local 기능은 여전히 mock recipe 데이터에 의존합니다.**  
   - `packages/website/frontend/src/pages/Local/LocalPage.jsx:3,62-63`  
   - `packages/website/frontend/src/data/mockData.js:40-99`  
   - 실시간 동네 탐색 화면 안에 정적 레시피 비용이 섞여 있어 기능 완성도가 들쭉날쭉합니다.

8. **crawler-admin 대시보드의 activeCrawlers 수치는 실제 active가 아니라 total 복사본입니다.**  
   - `packages/crawler-admin/backend/api/routes/dashboard.py:209-214`  
   - 운영 지표를 보여주는 화면에서 숫자를 대충 채우는 건 위험합니다.

9. **crawler-admin 스케줄 실행 버튼은 실패를 UI에서 거의 무시합니다.**  
   - `packages/crawler-admin/frontend/src/pages/Schedule/Schedule.jsx:178-187`  
   - catch에서 아무 메시지도 주지 않고 잠깐 “실행 중...”만 보여줍니다. 실패를 성공처럼 보이게 하는 UX입니다.

10. **db-admin는 `REQUIRE_AUTH=false`일 때 익명 사용자를 admin으로 취급합니다.**  
   - `packages/db-admin/backend/api/auth.py:85-132`  
   - 기본값은 true지만, 개발 플래그가 한 번이라도 잘못 내려가면 권한 모델이 즉시 무너집니다. “우회 모드” 치고도 너무 위험합니다.

11. **플러그인 import guard whitelist가 과도합니다.**  
   - `packages/crawler-admin/backend/plugins/import_guard.py:48-85`  
   - `engine` 전체를 허용 목록에 넣는 순간 샌드박스 의도가 크게 약해집니다.

12. **문서가 현재 구현과 심하게 어긋납니다.**  
   - `README.md:85` — “전체 테스트 1,330개”  
   - `docs/STATUS.md:130-139` — skeleton을 완료로 표기  
   - `docs/API_CONTRACTS.md:29-41` — 공통 응답 형식 명시  
   - 실제로는 `crawler-admin`와 `db-admin`의 여러 라우트가 raw dict를 그대로 반환합니다. 예: `packages/crawler-admin/backend/api/routes/crawlers.py:129,173,218,322,361`, `packages/db-admin/backend/api/routes/auth_routes.py:54-55,75,84-98`.

13. **테스트가 현재 코드를 제대로 따라가지 못합니다.**  
   - `packages/website/backend/tests/test_api_routes.py:13-22`  
   - `packages/integration-tests/test_api_contracts.py:40-48,86-99`  
   - `packages/security-perf-tests/test_plugin_security.py:13-15,138-165`  
   - community 테스트는 지금은 안 쓰는 인메모리 상태를 리셋하고, integration test는 응답 구조만 훑으며, plugin security test는 실제 JS를 돌리는 게 아니라 Python mirror를 검증합니다.

14. **실행 검증 결과도 불안정합니다.**  
   - 실제 실행: `website backend pytest` 실패, `db-admin backend pytest` 307 passed / 555 warnings, `crawler-admin backend pytest` hang  
   - 프론트 빌드는 통과했지만 `crawler-admin`은 `683.24 kB` 번들 경고가 났습니다.

### 🔵 개선 (품질 향상을 위한 제안)
1. `website`가 `db-admin`의 모델/세션을 직접 import하지 못하게 하고, 정말 분리할 거면 **HTTP API 또는 shared contract**로만 통신하게 바꾸세요.
2. 인증은 **httpOnly secure cookie + 서버 측 세션/refresh 전략**으로 재설계하세요. 지금처럼 URL 쿼리 + sessionStorage는 방어가 약합니다.
3. 응답 포맷을 전 프로젝트에서 통일하세요. 지금은 `ApiResponse`, raw dict, nested success가 섞여 있습니다.
4. 검색/가격비교는 “보여주기용 집계”가 아니라 실제 total count, 실제 relevant sort, 실제 popularity metric을 쓰도록 다시 짜야 합니다.
5. 플러그인 시스템은 하나로 정리해야 합니다.  
   - crawler-admin: YAML 스캐너 vs PluginManager 통합  
   - website: SDK/Marketplace를 실제 라우트/화면에 붙이거나 과감히 범위에서 제외
6. 홈페이지는 `/api/dashboard` 하나로 줄이고, 섹션별 에러 상태도 dashboard 응답에서 내려주도록 정리하세요.
7. admin 패널은 “로그인 폼”만 만들지 말고, **초기 관리자 생성/부트스트랩 절차**를 명확히 제공해야 합니다.
8. 테스트는 “200이 나왔다”를 넘어 **실제 데이터 의미와 실패 시나리오**를 검증해야 합니다.

### 📊 프로젝트별 평가
| 프로젝트 | 코드 품질 | 기능 완성도 | UX | 보안 |
|---|---:|---:|---:|---:|
| `packages/website` | 4/10 | 5/10 | 5/10 | 3/10 |
| `packages/crawler-admin` | 5/10 | 4/10 | 4/10 | 4/10 |
| `packages/db-admin` | 6/10 | 7/10 | 6/10 | 5/10 |
| `packages/shared` | 5/10 | 6/10 | - | 5/10 |

### 🏗️ 아키텍처 평가
#### 1) 모듈 분리는 “폴더상 분리”일 뿐, 런타임 분리는 아닙니다
- `website`는 `db-admin` 없이 독립 배포 가능한 구조가 아닙니다.  
- `packages/website/backend/api/app.py:130-153`, `packages/website/backend/services/db.py:20-26`에서 보듯 상대 경로와 `sys.path` 해킹으로 `db-admin` 내부를 직접 끌어옵니다.  
- `docs/API_CONTRACTS.md:15-21`의 독립 서비스 다이어그램은 현재 코드 기준으로 사실과 다릅니다.

#### 2) API 계약은 문서가 아니라 “희망사항”에 가깝습니다
- 문서는 공통 `{success,data,error,meta}`를 말하지만, crawler-admin과 db-admin은 raw dict를 많이 반환합니다.  
- website 안에서도 `ApiResponse(data={"success": True})`처럼 envelope가 중첩됩니다 (`packages/website/backend/api/routes/hotdeals.py:158-162`).

#### 3) plugin 시스템은 end-to-end로 연결되지 않았습니다
- crawler-admin backend: plugin route는 YAML 스캔, plugin manager는 별도 생명주기 관리  
- website frontend: SDK/Marketplace/Host/Sandbox가 있으나 App 수준에서 실제 사용자 기능으로 노출되지 않음  
- 결론: **플러그인 기능이 제품 기능으로 닫히지 않았습니다.**

#### 4) 상태 저장 전략이 너무 즉흥적입니다
- crawler-admin은 상태/이력/스케줄/설정을 JSON 파일에 저장합니다 (`crawler_status.json`, `crawler_run_history.json`, `schedules.json`, `crawler_settings.json`).  
- 소규모 데모에는 버틸 수 있지만, 관리 패널/스케줄러/실시간 상태 시스템으로서는 내구성과 동시성 측면에서 빈약합니다.

#### 5) 프론트-백엔드 연결도 일관성이 부족합니다
- homepage는 dashboard endpoint를 무시하고 8개 요청을 날립니다.  
- hotdeal/community/local은 직접 `fetch`와 store, service 계층이 뒤섞입니다.  
- 서비스 레이어에는 실제 없는 API가 남아 있습니다.  
- 즉, 구조가 “정리된 아키텍처”라기보다 **기능별로 각자 자란 흔적**에 가깝습니다.

### 📋 다음 단계 권장 사항
#### P0
1. `packages/website/backend/.env`에서 노출된 secret 즉시 폐기/재발급
2. OAuth 토큰 URL 전달 제거, cookie 기반으로 재구성
3. `website`의 `db-admin` 직접 import 제거
4. `website backend` 앱 초기화(import path)부터 정상화하여 pytest가 기본적으로 돌게 만들기
5. crawler-admin 로그인 검증 로직(`/health`) 즉시 수정

#### P1
1. 검색/가격비교/커뮤니티 정렬·pagination을 “진짜 동작”하도록 재구현
2. `/api/dashboard`를 homepage에서 실제 사용
3. hotdeal 투표/댓글의 인증 정책 정리
4. plugin route와 PluginManager 통합
5. Docker compose와 문서 전면 정리

#### P2
1. 죽은 서비스 레이어 제거 (`productService.compareProducts`, `authService.socialLogin`, `hotdealService.submitDeal` 등)
2. placeholder UI(약관, 프로필, 알림) 정리
3. 테스트를 실동작 중심으로 재작성
4. `datetime.utcnow()` 등 경고 정리

