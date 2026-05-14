# 구현 코드 리뷰 보고서 (GPT-5.4)

## 전체 평가
등급: **C+**

백엔드 단위 테스트(`packages\website\backend`: `45 passed`)와 프론트엔드 빌드는 통과했지만, **프론트-백엔드 계약 불일치가 매우 많아 실제 기능은 여러 곳에서 깨집니다.** 특히 프로필/활동내역/장바구니/찜 기능은 라우트·필드명·응답 shape가 서로 맞지 않아 로그인 후 실사용 시 실패할 가능성이 높습니다.

## 🔴 즉시 수정 필요
1. **소프트 삭제 계정이 계속 로그인/사용 가능합니다**
   - 파일: `packages/website/backend/api/routes/profile.py:116-129`, `packages/website/backend/api/routes/auth.py:90-99`, `packages/website/backend/api/middleware/auth.py:24-35`
   - 문제: `DELETE /api/profile`는 `is_deleted=True`만 설정하지만, 로그인과 인증 미들웨어는 `is_deleted`를 전혀 확인하지 않습니다. 삭제된 계정이 다시 로그인하거나 기존 JWT로 장바구니/찜/API를 계속 사용할 수 있습니다.
   - 제안: 로그인/OAuth/me/require_auth 단계에서 `is_deleted` 또는 `is_active`를 강제 확인하고, 삭제 시 토큰 무효화/쿠키 정리도 같이 처리하세요.

2. **프로필 페이지가 존재하지 않는 API를 호출합니다**
   - 파일: `packages/website/frontend/src/pages/Profile/ProfilePage.jsx:67-69,89-94,118`, `packages/website/frontend/src/services/authService.js:29-31`
   - 문제: 프론트는 `/api/activity/me`, `/api/auth/me`(PUT/DELETE)를 호출하지만, 백엔드는 `/api/profile/activity`, `/api/profile`만 제공합니다. 또한 `profile_image`를 보내지만 백엔드는 `profile_image_url`을 받습니다.
   - 제안: 프로필 저장/삭제/활동 조회를 모두 `/api/profile*`로 맞추고, 응답의 `data` 래퍼도 함께 반영하세요.

3. **활동 추적이 저장되지 않고 활동 탭도 렌더링이 틀립니다**
   - 파일: `packages/website/frontend/src/hooks/useActivityTracker.js:22-27`, `packages/website/frontend/src/pages/Profile/ProfilePage.jsx:266-279`, `packages/website/backend/api/routes/activity.py:80-113`, `packages/website/backend/api/routes/profile.py:153-160`
   - 문제: 프론트는 `event_type`을 보내고 읽지만, 백엔드는 `activity_type`만 사용합니다. 결과적으로 추적 POST는 400이 나고, 프로필 활동 탭도 빈 상태로 보입니다.
   - 제안: 프론트 전부 `activity_type`으로 통일하고, 프로필 탭은 `/api/profile/activity`의 `data/meta` shape를 그대로 사용하세요.

4. **장바구니 스토어가 로그인 상태를 잘못 판별해 서버 동기화가 사실상 동작하지 않습니다**
   - 파일: `packages/website/frontend/src/stores/cartStore.js:18-29,32-34,76-87`, `packages/website/frontend/src/stores/appStore.js:149-157`
   - 문제: `cartStore._getAuth()`는 localStorage의 `wallet-savior-store.state.isLoggedIn`을 읽는데, `appStore`의 persist 대상에는 `isLoggedIn`/`user`가 없습니다. 따라서 항상 false가 되어 로그인 후에도 `fetchCart`, `addItem`, `updateQuantity`, `removeItem`이 API를 거의 호출하지 않습니다.
   - 추가 문제: API 응답을 `data.items || data`로 읽어 `ApiResponse` 전체 객체를 `items`에 넣을 수 있고, 백엔드 필드(`item_name`, `item_price`)도 프론트 필드(`name`, `price`)로 정규화하지 않습니다.
   - 제안: 인증 여부는 runtime store 또는 `/api/auth/me` 결과로 판별하고, 장바구니 API 응답은 `data.data`를 꺼낸 뒤 프론트 shape로 변환하세요.

5. **찜 목록 페이지도 응답 shape/식별자 계약이 틀려 삭제·수정이 오동작합니다**
   - 파일: `packages/website/frontend/src/pages/Wishlist/WishlistPage.jsx:47-49,69,88,159-166`, `packages/website/backend/api/routes/wishlist.py:44-57`
   - 문제: 프론트는 `data.items`, `wishlist_id`, `product_name`, `image`를 기대하지만, 백엔드는 `data`, `id`, `item_name`, `item_image_url`을 반환합니다. 특히 삭제/수정 시 `product_id`를 path에 넣어 `DELETE /api/wishlist/{product_id}`를 호출할 수 있어 잘못된 row를 건드리거나 404가 납니다.
   - 제안: 프론트에서 `item.id`를 식별자로 사용하고, 백엔드 응답을 한 번 정규화한 뒤 렌더링하세요.

6. **상품 상세 모달이 없는 백엔드 엔드포인트를 호출합니다**
   - 파일: `packages/website/frontend/src/components/ProductDetailModal.jsx:79-86,121-127`, `packages/website/frontend/src/pages/Home/HomePage.jsx:536-545,753-756`, `packages/website/backend/api/routes/products.py:491-531`
   - 문제: 모달은 `/api/products/{id}/comparison`, `/other-stores`를 호출하지만 백엔드엔 `/price-compare`만 있습니다. 게다가 홈은 핫딜/마트 데이터를 `ProductDetailModal`에 넘겨 실제 product id가 아닌 id로 `/api/products/*`를 조회합니다.
   - 제안: 모달을 “실제 Product 전용”으로 제한하거나, 현재 백엔드 계약에 맞는 엔드포인트/응답 shape로 다시 맞추세요.

## 🟡 주의 필요
1. **OAuth 자동 연동이 기존 로컬 계정을 탈취 경로로 만들 수 있습니다**
   - 파일: `packages/website/backend/api/routes/auth.py:216-237`
   - 문제: 동일 이메일의 기존 계정이 있으면 별도 본인확인 없이 OAuth 계정을 바로 링크합니다.
   - 제안: 비밀번호 계정에는 자동 링크를 금지하고, 별도 계정 연결 절차를 두세요.

2. **인증된 GET 응답 캐시가 사용자 간 데이터 노출을 일으킬 수 있습니다**
   - 파일: `packages/website/frontend/src/services/api.js:47-63,181-190`, 사용처 `WishlistPage.jsx:47`, `ProfilePage.jsx:67`
   - 문제: 캐시 키에 사용자 정보가 없고 로그아웃 시 캐시도 비우지 않습니다. 같은 브라우저에서 A 로그아웃 직후 B가 로그인하면 30초 동안 A의 찜/활동 데이터가 재사용될 수 있습니다.
   - 제안: 인증 API는 캐시 제외하거나, 로그인/로그아웃 시 `_cache.clear()` 하세요.

3. **런타임 산출물이 저장소에 커밋되었습니다**
   - 파일: `packages/db-admin/backend/walletguardian.db`, `logs/audit.jsonl`, `packages/crawler-admin/backend/logs/*.jsonl` 등
   - 문제: DB/로그 파일은 용량 증가, merge 충돌, 개인정보 유출 위험이 큽니다.
   - 제안: 추적 해제 후 `.gitignore`로 제외하세요.

## 🔵 개선 제안
1. 새 기능(프로필/장바구니/찜/활동추적)에 대해 **프론트-백엔드 통합 테스트**를 추가하세요. 현재 백엔드 단위 테스트는 통과하지만 계약 mismatch를 잡지 못했습니다.
2. `wishlist_items`에 `(user_id, product_id)` 유니크 제약을 두는 편이 안전합니다. 현재는 동시 요청 시 중복 저장 가능성이 있습니다.
3. cookie 기반 인증으로 이동했으므로, 운영 환경에서 `CORS_ORIGINS` 검증과 auth 관련 캐시/에러 처리 정책을 한 번 더 정리하는 것이 좋습니다.

## 🟤 에이전트 간 충돌
- **백엔드 Agent**는 `ApiResponse(data=...)`, `/api/profile`, `activity_type`, `id/item_name/item_image_url` 계약을 구현했습니다.
- **프론트엔드 Agent**는 `data.items`, `/api/auth/me`(PUT/DELETE), `/api/activity/me`, `event_type`, `wishlist_id/product_name/image` 계약을 전제로 작성했습니다.
- **UX Agent/HomePage**는 핫딜/마트 객체를 `ProductDetailModal`에 넘겼지만, 모달은 실제 `Product` API를 호출합니다.

즉, 이번 라운드의 가장 큰 문제는 **개별 구현 품질보다 계약 합의 실패**입니다.

## ✅ 잘된 점
- 백엔드 auth guard 자체는 대부분 신규 라우트에 잘 붙어 있습니다.
- 프로필/장바구니/찜/활동추적에 대한 백엔드 테스트가 추가되었고, 해당 테스트는 실행 시 통과했습니다.
- 프론트엔드 빌드는 정상 통과하여 문법/번들링 수준의 충돌은 없습니다.
- 카테고리 요약, 활동 추천, 상품 상세 모달 등 사용자 가치가 큰 기능 방향은 좋습니다.

## 📋 수정 우선순위
1. 프론트-백엔드 계약서부터 재정렬: **프로필/활동/장바구니/찜 API path + 필드명 + 응답 shape 통일**
2. 소프트 삭제 계정 재로그인/재사용 차단
3. `cartStore`/`WishlistPage` 정규화 레이어 추가 및 로그인 동기화 수정
4. `ProductDetailModal`을 실제 백엔드 엔드포인트에 맞게 재설계
5. 인증 GET 캐시 제거 또는 사용자 단위 분리
6. DB/로그 파일 추적 해제
