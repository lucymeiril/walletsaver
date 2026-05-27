# Round U 웹 프론트 시점 롤백 보고서

## 채택 commit
- `eca2c9c feat(web-frontend): mcp2 웹 피처 워크스루 — sort UI 추가 및 key prop 수정`
- `abf6ff8`와 페이지 목록/App 라우트가 동일했고, `eca2c9c`는 이후 Home 검색 정렬 UI와 key prop 수정만 추가되어 더 안전한 후보로 채택.

## 복구된 화면/메뉴
- 페이지 목록: Home, Category, ProductDetail, FuelStations, BoardList, Board, NewPost, PostDetail, Login, Register, Account, Admin.
- 상단 메뉴에 발표용 5개 핵심 탭 노출:
  - 동네 물가
  - 마트 비교
  - 카테고리
  - 주유소
  - 게시판
- `/fuels` 라우트가 빠져 있어 `FuelStationsPage`를 App 라우트에 연결.
- `마트 비교`는 dedicated compare endpoint를 새로 만들지 않고, 옛 Home/핫딜 그리드로 안전하게 진입시키는 시각 메뉴로 처리.

## Backend 호환성 점검
`packages/web-frontend/src/api/client.ts` 호출 endpoint와 현재 `packages/web-api/backend/api/routes/` 매칭:

- OK: `/api/v1/health` → `health.py`
- OK: `/api/v1/categories` → `categories.py`
- OK: `/api/v1/products/search`, `/api/v1/products/{canonical_id}` → `products.py`
- OK: `/api/v1/autocomplete` → `autocomplete.py`
- OK: `/api/v1/fuels/regions`, `/api/v1/fuels/stations`, `/api/v1/fuels/stations/{station_id}` → `fuels.py`
- OK: `/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/logout`, `/api/v1/auth/me` → `auth.py` prefix `/auth`
- OK: `/api/v1/boards`, `/api/v1/boards/{slug}/categories`, `/api/v1/boards/{slug}/posts`, `/api/v1/posts/{id}`, comments/report/verdict endpoints → `boards.py`
- OK: `/api/v1/reports`, `/api/v1/reports/{id}/resolve`, `/api/v1/users/{id}/ban`, `/api/v1/users/{id}/unban`, `/api/v1/admin/audit` → `moderation.py`

## Risk
- Backend 코드는 변경하지 않음.
- 데이터 DB/스냅샷 부재 시 상품 API가 503을 낼 수 있으나 Home은 핫딜 로딩 실패 시 빈 상태로 fallback.
- 로그인 필요한 글쓰기/관리 기능은 미로그인 상태에서 401 가능. 발표용 디자인/탭 노출에는 영향 없음.

## Build
- `npm install --no-audit --no-fund`: up to date.
- `npm run build`: 성공.
  - `tsc -b && vite build`
  - `✓ 196 modules transformed.`
  - `✓ built in 301ms`
