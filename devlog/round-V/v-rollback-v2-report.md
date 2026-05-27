# Round V rollback v2 report

## Summary
- `git checkout abf6ff8 -- packages\web-frontend`로 웹 프론트엔드를 5/24 이전 기준(F4, 5/17)으로 롤백했다.
- `packages\web-frontend`에서 `npm install --no-audit --no-fund` 및 `npm run build`를 실행했고 성공했다.
- backend(`packages\web-api`) 코드는 수정하지 않았다.

## Build verification
```text
npm install --no-audit --no-fund
# up to date

npm run build
# tsc -b && vite build
# ✓ 196 modules transformed.
# ✓ built in 337ms
```

## Endpoint compatibility check
`packages\web-frontend\src\api\client.ts` 호출 목록과 `packages\web-api\backend\api\routes\` 라우트를 대조했다.

| Frontend call | Backend route | Result |
| --- | --- | --- |
| `GET /api/v1/health` | `health.py` `/health` | OK |
| `GET /api/v1/categories` | `categories.py` `/categories` | OK |
| `GET /api/v1/products/search` | `products.py` `/products/search` | OK |
| `GET /api/v1/products/{canonicalId}` | `products.py` `/products/{canonical_id}` | OK |
| `GET /api/v1/autocomplete` | `autocomplete.py` `/autocomplete` | OK |
| `GET /api/v1/fuels/regions` | `fuels.py` `/fuels/regions` | OK |
| `GET /api/v1/fuels/stations` | `fuels.py` `/fuels/stations` | OK |
| `GET /api/v1/fuels/stations/{stationId}` | `fuels.py` `/fuels/stations/{station_id}` | OK |
| `POST /api/v1/auth/register` | `auth.py` `/auth/register` | OK |
| `POST /api/v1/auth/login` | `auth.py` `/auth/login` | OK |
| `POST /api/v1/auth/logout` | `auth.py` `/auth/logout` | OK |
| `GET /api/v1/auth/me` | `auth.py` `/auth/me` | OK |
| `GET /api/v1/boards` | `boards.py` `/boards` | OK |
| `GET /api/v1/boards/{slug}/categories` | `boards.py` `/boards/{slug}/categories` | OK |
| `GET/POST /api/v1/boards/{slug}/posts` | `boards.py` `/boards/{slug}/posts` | OK |
| `GET/DELETE /api/v1/posts/{id}` | `boards.py` `/posts/{post_id}` | OK |
| `POST /api/v1/posts/{postId}/comments` | `boards.py` `/posts/{post_id}/comments` | OK |
| `POST /api/v1/posts/{postId}/report` | `boards.py` `/posts/{post_id}/report` | OK |
| `POST /api/v1/comments/{commentId}/report` | `boards.py` `/comments/{comment_id}/report` | OK |
| `GET /api/v1/posts/{postId}/verdict-summary` | `boards.py` `/posts/{post_id}/verdict-summary` | OK |
| `GET /api/v1/reports` | `moderation.py` `/reports` | OK |
| `POST /api/v1/reports/{id}/resolve` | `moderation.py` `/reports/{report_id}/resolve` | OK |
| `POST /api/v1/users/{id}/ban` | `moderation.py` `/users/{user_id}/ban` | OK |
| `POST /api/v1/users/{id}/unban` | `moderation.py` `/users/{user_id}/unban` | OK |
| `GET /api/v1/admin/audit` | `moderation.py` `/admin/audit` | OK |

누락 endpoint는 발견하지 못했다. 따라서 backend endpoint 추가나 frontend 비활성화 처리는 하지 않았다.

## NavBar check
메인 NavBar에 다음 5탭이 노출되도록 확인/보정했다.

- 동네물가
- 마트비교
- 카테고리
- 주유소
- 게시판

보정 파일:
- `packages\web-frontend\src\components\NavBar.tsx`
- `packages\web-frontend\src\App.tsx` (`/fuels` route 연결)
- `packages\web-frontend\src\pages\HomePage.tsx` (`#categories` anchor)

## Notes
- commit은 생성하지 않았다.
- 이번 슬롯에서는 backend(`web-api`) 코드와 다른 패키지(`db-admin`, `crawler-admin`) 파일을 편집하지 않았다. 작업 전부터 존재하던 dirty state는 보존했다.
