# WalletSavior 코드 품질 / UX 감사 보고서

> 감사일: 2026-04-15 | 감사 모델: GPT-5.4 | 대상: walletSavior 전체 monorepo

---

## 1. 🔴 심각 (Critical)

### 1.1 website 백엔드가 db-admin 소스/DB에 직접 결합됨
- **파일**: `packages/website/backend/api/app.py:131-153`, `services/db.py:20-26`, `api/routes/community.py:38-68`
- **문제**: website가 API 호출이 아니라 `sys.path` 삽입 + `db-admin/backend/walletguardian.db` 직접 접근으로 동작. 동일 SQLite를 여러 백엔드가 직접 읽고/쓰기 하므로 배포/테스트/락 충돌 위험.
- **스니펫**: `sys.path.insert(0, db_admin_path)`, `_DEFAULT_DB_URL = f"sqlite:///{Path(_db_admin_backend) / 'walletguardian.db'}"`

### 1.2 db-admin 인증이 기본 비활성화 + 익명 admin 취급
- **파일**: `packages/db-admin/backend/config.py:37-39`, `api/auth.py:85-92,130-132`
- **문제**: `REQUIRE_AUTH=false` 기본값, 이 경우 익명 identity가 `role: "admin"`. 관리자 패널 전체가 무인증.

### 1.3 crawler-admin 파이프라인 URL 하드코딩 + 잘못된 포트
- **파일**: `packages/crawler-admin/backend/pipeline/pipeline.py:33-38`, `api/routes/ingestion.py:22-24`
- **문제**: 저장 API URL이 `8001`(crawler-admin 자기 자신)으로 향함. db-admin은 `8002`인데 설정 불일치.

### 1.4 website 핫딜 댓글/투표가 인메모리 더미로 폴백
- **파일**: `packages/website/backend/api/routes/hotdeals.py:123-131,156-216`
- **문제**: 투표 실패 시 가짜 카운트 반환, 댓글은 `_hotdeal_comments` 메모리 dict. 서버 재시작 시 유실.

### 1.5 커뮤니티 댓글 렌더링 필드명 불일치 (프론트 ↔ 백엔드)
- **프론트**: `CommunityPage.jsx:849-853` → `c.author`, `c.time`, `c.text`
- **백엔드**: `community.py:103-113` → `content`, `author_nickname`, `created_at`
- **문제**: 실제 댓글이 비어 보이거나 작성자/시간 표시 깨짐.

### 1.6 커뮤니티 상품선택/태그 UI가 저장 payload에 미반영
- **파일**: `CommunityPage.jsx:138-147,230-238`
- **문제**: `wSelectedProducts`, `wTag` 상태는 있으나 POST payload에 `product_id`, `tag` 없음. UI만 존재.

### 1.7 ProductPicker가 자동완성 API 응답 형식과 불일치
- **프론트**: `ProductPicker.jsx:25-30` → `res.data`를 배열로 가정
- **백엔드**: `search.py:158-166` → `{ keywords, products, ... }` 구조 반환
- **문제**: 상품 검색 모달 동작 불량.

### 1.8 검색 결과 클릭이 상세 대상과 미연결
- **파일**: `SearchPage.jsx:93-98`
- **문제**: 핫딜/커뮤니티 결과 클릭 시 `/hotdeal`, `/community`로만 이동. item id를 state로 넘기지 않아 상세 진입 불가.

### 1.9 필수 의존성 누락으로 런타임 ImportError 위험
- website: `playwright` 없음 (`naver_local.py` 사용)
- crawler-admin: `PyYAML` 없음 (`plugins.py` 사용)
- db-admin: `python-jose`, `passlib[bcrypt]` 없음 (`auth.py` 사용)

---

## 2. 🟡 경고 (Warning)

### 2.1 홈 커뮤니티 섹션 필터 파라미터명 불일치
- 프론트: `board=hotdeal`, 백엔드: `post_type` 파라미터. 핫딜 게시판 필터 미동작 가능.

### 2.2 사용자 프로필 API가 하드코딩 데이터 반환
- `packages/website/backend/api/routes/users.py:36-58` — `created_at` 고정값, PUT도 실제 저장 안 함.

### 2.3 크롤러 실행 API는 TODO 스텁
- `packages/website/backend/api/routes/crawlers.py:64-72` — `# TODO: engine.execute_crawler(name)`

### 2.4 Local/Recipe 기능에 목업 데이터 잔존
- `mockData.js:15-91`, `LocalPage.jsx:3,62-63`, `restaurants.py:102-109`

### 2.5 공유 기능 미완성
- `ShareButton.jsx:32-45` — 카카오 공유 `// TODO: Kakao SDK 초기화 후 활성화`

### 2.6 플러그인 시스템은 UI/테스트 전용
- `PluginHost.jsx`, `PluginMarketplace` 구현은 있으나 App/페이지에서 렌더링하지 않음.

### 2.7 커스텀 모달 접근성/키보드 UX 미흡
- Community/Hotdeal 상세가 공통 Modal 미사용. focus trap/Esc/aria 불완전.

### 2.8 비밀번호 토글 키보드 접근 불가
- `Input.jsx:35-40` — `tabIndex={-1}`로 키보드 사용자 접근 차단.

### 2.9 검색 UX: 결과 상세 컨텍스트 상실 + 페이지네이션 컨트롤 없음

### 2.10 검색 트래킹이 상품 id를 keyword_id로 재사용
- `trackKeyword`는 keyword_id용인데 상품 클릭에도 `p.id`를 넘겨 검색 통계 오염.

### 2.11 crawler-admin 플러그인 카테고리 필터 불일치
- 프론트: `'마트'`, `'핫딜'` (한글), 백엔드: `'mart'`, `'hotdeal'` (영문). 필터 미동작.

### 2.12 crawler-admin / db-admin 프론트에 로그인 UI 없음
- `REQUIRE_AUTH=true` 전환 시 인증 헤더 주입 로직 없어 즉시 깨짐.

### 2.13 silent catch / 오류 삼킴 다수
- `App.jsx:64,72`, `AuthCallback.jsx:41-43`, `search.py:91-92` 등 — `.catch(() => {})`, `except Exception: pass`

### 2.14 N+1 / 비효율 조회
- db-admin 상품 목록: 상품마다 최신 가격/소스 개별 조회
- website 커뮤니티: 각 post마다 votes/comments 관계 순회
- 식당 검색: 최대 1000건 메모리 로드 후 거리 계산

### 2.15 API 응답 형식 비일관
- `ApiResponse`, raw dict, raw list 혼재. 프로젝트/엔드포인트마다 다른 구조.

### 2.16 API 버저닝 부재
- 모든 경로 `/api/...`이며 breaking change 관리 불가.

### 2.17 테스트 품질 문제
- 구현 세부 의존, CSS 클래스 의존, 무의미 assertion, 시간 의존 flaky 패턴.

---

## 3. 🟢 개선 (Info)

### 3.1 프론트엔드 타입 안정성 낮음
- 3개 프론트 모두 JS/JSX 기반. PropTypes/TypeScript 미사용.

### 3.2 unused / dead code 다수
- website: 루트 레벨 중복 페이지 파일 (새 폴더형과 병존)
- crawler-admin/db-admin: `mockData.js`가 import 없이 존재

### 3.3 localService가 실제 페이지에서 미사용 + 중복 구현
- 서비스로 분리돼 있으나 페이지에서 fetch 루프를 직접 재구현.

### 3.4 서비스 레이어 있는데 raw fetch 남용
- searchService, productService 등 존재하나 페이지에서 직접 `fetch` 호출.

---

## 4. 테스트 커버리지 공백

### website
- **백엔드 미검증**: `users.py`, `restaurants.py`, `search.py`, `crawlers.py`, `marts.py` flyer 경로
- **프론트엔드**: `Button/Input/Modal/useDebounce/plugins` 위주. pages/services/stores 대부분 무테스트

### crawler-admin
- **프론트엔드**: 페이지 단위 테스트 없음
- **백엔드**: `plugins.py`, `logs.py`, `dashboard.py`, `ingestion.py` 직접 API 계약 테스트 부족

### db-admin
- **프론트엔드**: 페이지 테스트 없음
- **백엔드**: `products.py`, `prices.py`, `ingestion.py`, `analytics.py`, `dashboard.py` API 계약 테스트 부족

---

## 5. 우선순위 권고

### 즉시 차단 (P0)
1. db-admin 무인증 admin 기본값 수정
2. website의 db-admin 직접 파일/DB 결합 제거 (API 호출로 전환)
3. crawler-admin 파이프라인 URL/포트 수정
4. 누락 의존성 추가 (`playwright`, `PyYAML`, `python-jose`, `passlib[bcrypt]`)

### 기능 완성 (P1)
1. 커뮤니티: product/tag/comment 필드 계약 정리
2. 핫딜 댓글/투표 DB 영속화 + 인증 추가
3. 검색 결과 → 특정 핫딜/게시글 상세 연결
4. 홈 커뮤니티 필터 파라미터 수정
5. 사용자 프로필 API 실제 DB 연동

### 코드 품질 (P2)
1. silent catch 제거, 적절한 에러 표시
2. 서비스 레이어로 fetch 통합
3. N+1 쿼리 최적화
4. API 응답 형식 통일
5. dead code 정리
6. 모달 접근성/키보드 UX 개선
