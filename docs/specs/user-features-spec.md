# WalletSavior (지갑 지키미) — 사용자 기능 설계 명세서

> **문서 버전:** 1.0  
> **작성일:** 2025-07-16  
> **분류:** PLANNING (구현 코드 없음 — 설계 문서)  
> **대상 독자:** 프론트엔드/백엔드 개발자, DB 관리자, PM  
> **현행 코드 베이스:** `packages/db-admin/backend/storage/models.py`, `packages/website/`

---

## 목차

1. [회원정보 시스템 (User Profile System)](#1-회원정보-시스템)
2. [장바구니 & 찜 목록 (Cart & Wishlist)](#2-장바구니--찜-목록)
3. [추천 알고리즘 데이터 수집 (Recommendation Data)](#3-추천-알고리즘-데이터-수집)
4. [마트 상품 상세 모달 (Mart Product Detail Modal)](#4-마트-상품-상세-모달)
5. [카테고리 자동 분류 개선 (Auto-categorization Fix)](#5-카테고리-자동-분류-개선)
6. [주유소 정보 개선 (Gas Station Enhancement)](#6-주유소-정보-개선)
7. [홈 → 상품 네비게이션 (Home → Product Navigation)](#7-홈--상품-네비게이션)
8. [DB 성능 설계 (DB Performance Design)](#8-db-성능-설계)

---

## 현행 시스템 상태 요약

| 영역 | 현재 상태 | 핵심 문제 |
|------|-----------|-----------|
| **User 모델** | `users` 테이블 존재, JWT + OAuth 인증 동작 | 프로필 수정 API 닉네임만 가능, 비밀번호 변경/계정삭제 없음 |
| **장바구니** | ❌ 미구현 (DB 스키마·API 없음) | 프론트 로컬 상태만 있음, 서버 미동기화 |
| **찜 (Favorite)** | ✅ `favorites` 테이블 + CRUD API | 상품 이미지·가격·출처 등 부가정보 없음 |
| **가격 알림** | ⚠️ 스키마만 존재, 트리거/알림 미구현 | `last_triggered` 갱신 안 됨 |
| **마트 상품** | 이름+가격만 표시, 상세 모달 없음 | `category_id` 24/1171 채워짐, `attributes` 0/1171 |
| **카테고리 분류** | `PendingCategorization` 스키마 존재 | 삼겹살 Homeplus만 표시 (Emart/Lotte 누락) |
| **주유소** | 8건 샘플 데이터, Opinet 실시간 연동 미확인 | `GasStation` 스키마 존재하나 빈 데이터 |
| **홈→상품** | 홈에서 마트 탭으로 이동하지만 특정 상품으로 포커스 안 됨 | URL 상태 관리 없음 |

---

# 1. 회원정보 시스템

## 1.1 기능 요구사항

### FR-USER-001: 프로필 페이지

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-USER-001-a | 사용자는 자신의 프로필 정보(닉네임, 이메일, 프로필 이미지, 가입일, 역할)를 조회할 수 있다 | P0 |
| FR-USER-001-b | 프로필 페이지에서 활동 요약(작성글 수, 댓글 수, 투표 수, 찜 수)을 확인할 수 있다 | P1 |
| FR-USER-001-c | 연동된 OAuth 계정 목록(Google, Kakao, Naver)을 확인할 수 있다 | P1 |

### FR-USER-002: 프로필 수정

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-USER-002-a | 닉네임을 변경할 수 있다 (2~20자, 중복 불가, 30일 1회 제한) | P0 |
| FR-USER-002-b | 프로필 이미지를 업로드/변경할 수 있다 (최대 2MB, jpg/png/webp) | P1 |
| FR-USER-002-c | 관심 카테고리(최대 5개)를 설정할 수 있다 | P2 |
| FR-USER-002-d | 기본 지역(위도/경도 or 주소)을 설정할 수 있다 | P2 |

### FR-USER-003: 계정 설정

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-USER-003-a | 이메일 주소를 변경할 수 있다 (인증 메일 발송 후 확인) | P1 |
| FR-USER-003-b | 비밀번호를 변경할 수 있다 (현재 비밀번호 확인 필수) | P0 |
| FR-USER-003-c | 계정을 탈퇴할 수 있다 (30일 유예기간, soft-delete) | P1 |
| FR-USER-003-d | OAuth 계정을 연동/해제할 수 있다 | P2 |

### FR-USER-004: 활동 내역

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-USER-004-a | 내가 작성한 게시글 목록을 페이지네이션으로 조회할 수 있다 | P1 |
| FR-USER-004-b | 내가 작성한 댓글 목록을 조회할 수 있다 | P1 |
| FR-USER-004-c | 내가 투표한 핫딜 목록을 조회할 수 있다 | P2 |
| FR-USER-004-d | 내 찜 목록/가격 알림 목록을 조회할 수 있다 | P1 |

## 1.2 데이터 모델

### 신규 테이블: `user_preferences`

```python
class UserPreference(Base):
    """사용자 개인 설정 — 관심 카테고리, 기본 지역, 알림 설정"""
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    preferred_categories: Mapped[Optional[list]] = mapped_column(JSON)
    # ["meat.pork", "vegetable.root", ...] — 최대 5개
    default_lat: Mapped[Optional[float]] = mapped_column(Float)
    default_lng: Mapped[Optional[float]] = mapped_column(Float)
    default_address: Mapped[Optional[str]] = mapped_column(String(300))
    notification_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_notification: Mapped[bool] = mapped_column(Boolean, default=True)
    push_notification: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship("User", backref="preference", uselist=False)
```

### 기존 `User` 모델 확장 필드

```python
# User 모델에 추가
nickname_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
# 닉네임 변경 30일 제한 체크용
deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
# soft-delete — None이면 활성, 값 있으면 탈퇴 유예 시작일
email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
```

### 신규 테이블: `email_verifications`

```python
class EmailVerification(Base):
    """이메일 변경/인증 토큰"""
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    new_email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_email_verify_token", "token"),
        Index("ix_email_verify_user", "user_id"),
    )
```

## 1.3 API 엔드포인트

### GET `/api/users/me/profile`

프로필 상세 + 활동 요약 + OAuth 계정 목록을 한 번에 반환.

```
Authorization: Bearer <JWT>

Response 200:
{
  "success": true,
  "data": {
    "id": 1,
    "email": "user@example.com",
    "nickname": "절약왕",
    "profile_image": "https://cdn.../avatar.jpg",
    "role": "user",
    "email_verified": true,
    "created_at": "2025-01-15T09:00:00Z",
    "preference": {
      "preferred_categories": ["meat.pork", "vegetable.root"],
      "default_address": "서울시 강남구",
      "notification_enabled": true
    },
    "oauth_accounts": [
      {"provider": "google", "linked_at": "2025-01-15T09:00:00Z"}
    ],
    "activity_summary": {
      "posts_count": 12,
      "comments_count": 45,
      "votes_count": 89,
      "favorites_count": 7,
      "alerts_count": 3
    }
  }
}
```

### PUT `/api/users/me/profile`

닉네임, 프로필 이미지, 선호 설정 통합 수정.

```
Authorization: Bearer <JWT>
Content-Type: multipart/form-data

Body:
  nickname: "새닉네임"              (optional)
  profile_image: <binary file>      (optional, max 2MB)
  preferred_categories: '["meat.pork","seafood"]'  (optional, JSON string)
  default_address: "서울시 서초구"   (optional)
  default_lat: 37.4967              (optional)
  default_lng: 127.0276             (optional)

Response 200:
{
  "success": true,
  "data": { ...updated user profile... }
}

Error 400: 닉네임 중복, 30일 미경과
Error 413: 이미지 크기 초과
Error 415: 허용되지 않는 이미지 형식
```

### PUT `/api/users/me/password`

```
Authorization: Bearer <JWT>
Content-Type: application/json

Body:
{
  "current_password": "old1234!",
  "new_password": "new5678!",
  "new_password_confirm": "new5678!"
}

Response 200: { "success": true, "message": "비밀번호가 변경되었습니다" }
Error 400: 현재 비밀번호 불일치, 새 비밀번호 정책 미달
Error 409: OAuth 전용 계정 (비밀번호 없음)
```

### POST `/api/users/me/email-change`

이메일 변경 요청 → 인증 메일 발송.

```
Authorization: Bearer <JWT>

Body: { "new_email": "newemail@example.com" }

Response 200: { "success": true, "message": "인증 메일을 발송했습니다" }
Error 409: 이미 사용 중인 이메일
```

### GET `/api/users/me/email-verify?token=<token>`

인증 메일 링크 클릭 시 이메일 변경 확정.

```
Response 200: { "success": true, "message": "이메일이 변경되었습니다" }
Error 400: 만료된 토큰, 이미 사용된 토큰
```

### DELETE `/api/users/me`

계정 탈퇴 (soft-delete).

```
Authorization: Bearer <JWT>

Body: { "password": "current1234!" }
   (OAuth-only 계정은 password 없이, "confirm": true)

Response 200:
{
  "success": true,
  "message": "30일 후 계정이 완전히 삭제됩니다. 로그인하면 탈퇴가 취소됩니다."
}
```

### GET `/api/users/me/activity`

활동 내역 통합 조회.

```
Authorization: Bearer <JWT>

Query Parameters:
  type: "posts" | "comments" | "votes" | "favorites" | "alerts"
  page: 1 (default)
  per_page: 20 (default, max 50)
  sort: "recent" | "popular" (default: "recent")

Response 200:
{
  "success": true,
  "data": {
    "items": [ ...type에 따라 다른 스키마... ],
    "pagination": {
      "page": 1,
      "per_page": 20,
      "total": 45,
      "has_next": true
    }
  }
}
```

### POST `/api/users/me/oauth/link`

OAuth 계정 추가 연동.

```
Authorization: Bearer <JWT>
Body: { "provider": "kakao" }

Response 200:
{
  "success": true,
  "data": { "authorize_url": "https://kauth.kakao.com/oauth/authorize?..." }
}
```

### DELETE `/api/users/me/oauth/{provider}`

OAuth 계정 연동 해제.

```
Authorization: Bearer <JWT>

Response 200: { "success": true }
Error 400: 유일한 인증 수단(비밀번호도 없는 경우)이면 해제 불가
```

## 1.4 프론트엔드 컴포넌트

```
pages/Profile/
├── ProfilePage.jsx              ← 메인 프로필 페이지 (탭 구조)
├── ProfilePage.module.css
├── tabs/
│   ├── ProfileInfoTab.jsx       ← 기본 정보 표시/수정
│   ├── AccountSettingsTab.jsx   ← 비밀번호, 이메일, 탈퇴
│   ├── ActivityTab.jsx          ← 내 게시글/댓글/투표
│   ├── FavoritesTab.jsx         ← 찜 목록 + 가격 알림
│   └── OAuthTab.jsx             ← OAuth 연동 관리
└── components/
    ├── ProfileImageUploader.jsx ← 이미지 업로드 + 크롭
    ├── NicknameEditor.jsx       ← 닉네임 변경 (중복 체크, 30일 제한)
    ├── CategoryPicker.jsx       ← 관심 카테고리 선택기 (최대 5개)
    ├── PasswordChangeForm.jsx   ← 비밀번호 변경 폼
    └── DeleteAccountModal.jsx   ← 탈퇴 확인 모달
```

**상태 관리:** 기존 `useStore()` (Zustand 추정) 확장.

```
profileStore:
  user: UserProfile | null
  preference: UserPreference | null
  activitySummary: ActivitySummary | null
  isLoading: boolean
  error: string | null
  actions:
    fetchProfile()
    updateProfile(data: Partial<UserProfile>)
    changePassword(current, new)
    requestEmailChange(newEmail)
    deleteAccount(password?)
    linkOAuth(provider)
    unlinkOAuth(provider)
```

**라우팅:**

```
/profile              → ProfilePage (기본: ProfileInfoTab)
/profile/settings     → ProfilePage (AccountSettingsTab)
/profile/activity     → ProfilePage (ActivityTab)
/profile/favorites    → ProfilePage (FavoritesTab)
/profile/oauth        → ProfilePage (OAuthTab)
```

## 1.5 보안 고려사항

| 위협 | 대응 |
|------|------|
| 프로필 이미지 악성 파일 업로드 | magic bytes 검증 + 이미지 리사이징 (Pillow) 후 저장, 원본 삭제 |
| 닉네임 XSS | HTML escape + 길이 제한 |
| 비밀번호 brute-force | 5회 실패 시 15분 잠금 (rate limiting) |
| 이메일 인증 토큰 탈취 | 토큰 1회용 + 24시간 만료 + HTTPS only |
| 탈퇴 유예 기간 무시 | scheduled job으로 30일 경과 계정만 hard-delete |
| OAuth 전용 계정 잠김 | 마지막 인증 수단 해제 차단 |

## 1.6 엣지 케이스

1. OAuth-only 계정이 비밀번호 변경 요청 → 409 반환 + "비밀번호 설정" 안내
2. 탈퇴 유예 중 재로그인 → `deleted_at` NULL로 복구, 알림 표시
3. 닉네임 변경 30일 이내 재요청 → 400 + 남은 일수 표시
4. 프로필 이미지 업로드 실패 시 기존 이미지 유지 (트랜잭션)
5. 동시 세션에서 닉네임 변경 → 먼저 커밋된 것이 승리, 후자 409
6. `preferred_categories`에 존재하지 않는 `category_id` → 검증 후 400

## 1.7 현행 시스템에서의 마이그레이션

```
현재:
  - PUT /api/users/me → 닉네임만 수정 가능
  - GET /api/auth/profile → 기본 정보만 반환
  - 프로필 이미지: 스키마 있지만 업로드 API 없음

마이그레이션 단계:
  1. user_preferences 테이블 생성 (Alembic migration)
  2. email_verifications 테이블 생성
  3. User 모델에 nickname_changed_at, deleted_at, email_verified 컬럼 추가
  4. 기존 PUT /api/users/me 확장 (하위 호환: 기존 닉네임만 보내도 동작)
  5. 새 엔드포인트 추가 (password, email-change, oauth/link 등)
  6. 프론트엔드 ProfilePage 신규 생성 + 라우터 등록
  7. 기존 GET /api/auth/profile 은 deprecated → /api/users/me/profile 로 리다이렉트
```

---

# 2. 장바구니 & 찜 목록

## 2.1 현재 문제 분석

현재 장바구니 항목은 "CJ 비건 프로틴 초코 250ML 수량 1개 2,900원" 같은 최소 정보만 표시한다.

**근본 원인:**
- 장바구니 DB 스키마 자체가 존재하지 않음
- 프론트엔드 로컬 상태(메모리/localStorage)에만 저장
- 상품 마스터(`products` 테이블)에 `image_url`, `attributes` 등이 채워져 있지 않음
- 찜(Favorite)은 DB에 있지만 `product_id`만 저장, 부가 정보 없음

## 2.2 기능 요구사항

### FR-CART-001: 장바구니 기본

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-CART-001-a | 장바구니에 상품 추가 시 다음 정보를 표시: 상품명, 이미지, 마트명, 카테고리, 원가, 할인가, 절약율, 출처 링크, 유효기간 | P0 |
| FR-CART-001-b | 장바구니 항목 클릭 → 상품 상세 모달 열기 OR 상품 페이지 이동 | P0 |
| FR-CART-001-c | 수량 변경, 항목 삭제, 전체 비우기 | P0 |
| FR-CART-001-d | 장바구니 합계 금액 / 총 절약 금액 표시 | P1 |
| FR-CART-001-e | 유효기간 만료 임박(24시간 이내) 항목 시각적 경고 | P2 |

### FR-CART-002: 장바구니 영속성

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-CART-002-a | 로그인 사용자: DB에 장바구니 저장 (디바이스 간 동기화) | P0 |
| FR-CART-002-b | 비로그인 사용자: localStorage 저장 → 로그인 시 DB로 병합 | P1 |
| FR-CART-002-c | 병합 시 중복 상품은 수량 합산, 충돌 시 최신 가격 우선 | P1 |

### FR-WISH-001: 찜 목록

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-WISH-001-a | 찜은 장바구니와 별도 — "가격 추적" 목적 | P0 |
| FR-WISH-001-b | 찜 항목에 가격 변동 추이(최근 7일) 미니 차트 표시 | P2 |
| FR-WISH-001-c | 가격 하락 시 알림 (기존 `PriceAlert` 연동) | P1 |
| FR-WISH-001-d | 찜 목록에서 장바구니로 이동 기능 | P1 |

## 2.3 데이터 모델

### 신규 테이블: `cart_items`

```python
class CartItem(Base):
    """장바구니 항목 — DB 영속 (로그인 사용자 전용)"""
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL")
    )
    # product_id가 NULL이면 외부 상품 (핫딜 등 우리 DB에 없는 상품)
    external_product_name: Mapped[Optional[str]] = mapped_column(String(300))
    external_product_url: Mapped[Optional[str]] = mapped_column(String(500))
    external_product_image: Mapped[Optional[str]] = mapped_column(String(500))

    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    original_price: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    # "emart" | "homeplus" | "lotte" | "costco" | "ppomppu" | "fmkorea" | ...
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    category_name: Mapped[Optional[str]] = mapped_column(String(100))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # 할인 유효기간 — NULL이면 상시

    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship("User", backref="cart_items")
    product: Mapped[Optional["Product"]] = relationship("Product")

    __table_args__ = (
        Index("ix_cart_user", "user_id"),
        Index("ix_cart_user_product", "user_id", "product_id"),
        Index("ix_cart_valid_until", "valid_until"),
    )
```

### 기존 `Favorite` 모델 확장

```python
# Favorite 모델에 추가할 필드:
note: Mapped[Optional[str]] = mapped_column(String(200))
# 사용자 메모 ("다음 할인 때 구매", "선물용 후보")
target_price: Mapped[Optional[float]] = mapped_column(Float)
# 목표 가격 — PriceAlert와 연동 (Favorite에서 바로 설정 가능)
last_price_check: Mapped[Optional[float]] = mapped_column(Float)
# 마지막으로 확인된 가격 — 변동률 계산용
last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
```

## 2.4 API 엔드포인트

### GET `/api/users/me/cart`

```
Authorization: Bearer <JWT>

Response 200:
{
  "success": true,
  "data": {
    "items": [
      {
        "id": 1,
        "product_id": 42,
        "product_name": "CJ 비건 프로틴 초코 250ML",
        "product_image": "https://cdn.emart.com/...",
        "source": "emart",
        "source_url": "https://emart.ssg.com/item/...",
        "category_name": "음료/프로틴",
        "quantity": 1,
        "unit_price": 2900,
        "original_price": 4500,
        "savings_percent": 35.6,
        "valid_until": "2025-07-20T23:59:59Z",
        "is_expiring_soon": false,
        "added_at": "2025-07-15T14:30:00Z"
      }
    ],
    "summary": {
      "total_items": 5,
      "total_price": 23400,
      "total_original_price": 38200,
      "total_savings": 14800,
      "savings_percent": 38.7,
      "expiring_soon_count": 1
    }
  }
}
```

### POST `/api/users/me/cart`

```
Authorization: Bearer <JWT>

Body:
{
  "product_id": 42,               (optional — 내부 상품)
  "external_product_name": null,   (optional — 외부 상품)
  "external_product_url": null,
  "external_product_image": null,
  "quantity": 1,
  "unit_price": 2900,
  "original_price": 4500,
  "source": "emart",
  "source_url": "https://emart.ssg.com/...",
  "category_name": "음료/프로틴",
  "valid_until": "2025-07-20T23:59:59Z"
}

Response 201: { "success": true, "data": { "id": 123, ...cart_item... } }
Error 400: product_id와 external_product_name 둘 다 없는 경우
Error 409: 동일 상품+source 이미 장바구니에 있으면 수량만 증가
```

### PATCH `/api/users/me/cart/{item_id}`

수량 변경.

```
Body: { "quantity": 3 }
Response 200: { "success": true, "data": { ...updated item... } }
Error 400: quantity < 1
Error 404: 해당 장바구니 항목 없음 또는 다른 사용자 소유
```

### DELETE `/api/users/me/cart/{item_id}`

```
Response 200: { "success": true }
```

### DELETE `/api/users/me/cart`

장바구니 전체 비우기.

```
Response 200: { "success": true, "deleted_count": 5 }
```

### POST `/api/users/me/cart/merge`

비로그인 상태 localStorage 장바구니 → 로그인 후 DB 병합.

```
Authorization: Bearer <JWT>

Body:
{
  "local_items": [
    {
      "product_id": 42,
      "quantity": 1,
      "unit_price": 2900,
      "source": "emart",
      ...
    }
  ]
}

Response 200:
{
  "success": true,
  "data": {
    "merged_count": 3,
    "conflict_count": 1,
    "conflicts": [
      {
        "product_id": 42,
        "local_price": 2900,
        "server_price": 3100,
        "resolved": "server_latest"
      }
    ],
    "cart": { ...full cart... }
  }
}
```

### 기존 찜 API 확장

### PUT `/api/users/me/favorites/{id}`

```
Body:
{
  "note": "다음 할인 때 구매",
  "target_price": 2500
}

Response 200: { "success": true, "data": { ...updated favorite... } }
```

### GET `/api/users/me/favorites` (확장)

기존 응답에 가격 정보 추가:

```
Response 200:
{
  "success": true,
  "data": {
    "items": [
      {
        "id": 1,
        "product_id": 42,
        "product_name": "삼겹살 (국내산)",
        "product_image": "https://...",
        "category_name": "축산물/돼지",
        "current_price": 15900,
        "last_price_check": 17200,
        "price_change": -7.6,
        "price_trend": "down",
        "target_price": 14000,
        "note": "다음 할인 때 구매",
        "created_at": "2025-07-01T10:00:00Z",
        "price_history_7d": [17200, 16800, 16500, 16000, 15900, 15900, 15900]
      }
    ],
    "pagination": { "page": 1, "per_page": 20, "total": 7 }
  }
}
```

## 2.5 프론트엔드 컴포넌트

```
components/Cart/
├── CartDrawer.jsx               ← 우측 슬라이드 패널 (장바구니 목록)
├── CartIcon.jsx                 ← 헤더 장바구니 아이콘 + 배지 카운트
├── CartItem.jsx                 ← 개별 장바구니 항목 (리치 카드)
├── CartSummary.jsx              ← 합계/절약 금액 요약
├── CartEmptyState.jsx           ← 빈 장바구니 안내
└── CartMergeDialog.jsx          ← 로그인 시 병합 확인 다이얼로그

components/Wishlist/
├── WishlistPage.jsx             ← 찜 목록 전체 페이지
├── WishlistItem.jsx             ← 개별 찜 항목 (가격 추이 미니차트 포함)
├── PriceTrendMini.jsx           ← 7일 가격 미니 라인 차트
├── WishlistTargetPriceInput.jsx ← 목표 가격 설정 인풋
└── MoveToCartButton.jsx         ← 찜 → 장바구니 이동
```

**상태 관리:**

```
cartStore:
  items: CartItem[]
  isLoading: boolean
  isOpen: boolean           // CartDrawer 열림/닫힘
  localItems: CartItem[]    // 비로그인 상태 localStorage
  actions:
    fetchCart()
    addItem(item)
    updateQuantity(itemId, quantity)
    removeItem(itemId)
    clearCart()
    mergeLocalCart()         // 로그인 후 호출
    toggleDrawer()
    get summary()            // computed: total, savings, count
```

## 2.6 보안 고려사항

| 위협 | 대응 |
|------|------|
| 다른 사용자 장바구니 접근 | 모든 cart API에서 `user_id == current_user.id` 검증 |
| 가격 조작 (클라이언트에서 unit_price 변조) | 서버에서 `product_id` 기반으로 최신 가격 검증, 오차 범위(10%) 초과 시 경고 로그 |
| 장바구니 대량 추가 DoS | 사용자당 최대 100개 항목 제한 |
| localStorage 장바구니 변조 | 병합 시 서버에서 가격/상품 재검증 |
| source_url 피싱 링크 삽입 | 허용 도메인 화이트리스트 (`emart.ssg.com`, `www.homeplus.co.kr`, ...) |

## 2.7 엣지 케이스

1. 장바구니에 있는 상품이 삭제됨 → `product_id` SET NULL, `external_product_name`으로 표시 유지
2. 할인 유효기간 만료된 항목 → "만료됨" 배지 + 가격 취소선 표시, 자동 삭제하지 않음
3. 동일 상품 다른 마트 → 별도 항목 (source로 구분)
4. 비로그인 → 로그인 시 localStorage에 50개, DB에 80개 → 100개 제한 → 오래된 것부터 제외, 사용자에게 알림
5. 찜의 `target_price`에 도달했지만 `PriceAlert` 테이블에 없는 경우 → 자동 생성

## 2.8 마이그레이션

```
1. cart_items 테이블 Alembic 마이그레이션 생성
2. favorites 테이블에 note, target_price, last_price_check, last_checked_at 컬럼 추가
3. User.cart_items relationship 추가
4. 장바구니 API 라우터 등록 (/api/users/me/cart)
5. 기존 찜 API 응답 확장 (가격 정보 추가 — 하위 호환)
6. 프론트엔드 CartDrawer + CartIcon 헤더에 추가
7. 프론트엔드 기존 shoppingList 상태 → cartStore로 마이그레이션
8. localStorage 마이그레이션: 기존 shoppingList 키 → cart_items 키로 변환
```

---

# 3. 추천 알고리즘 데이터 수집

## 3.1 기능 요구사항

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-REC-001 | 사용자의 검색 키워드 이력을 수집한다 | P0 |
| FR-REC-002 | 상품/카테고리 조회 이력을 수집한다 | P0 |
| FR-REC-003 | 장바구니 추가/제거 이벤트를 수집한다 | P1 |
| FR-REC-004 | 찜 추가/제거 이벤트를 수집한다 | P1 |
| FR-REC-005 | 핫딜 투표(Hot/Not) 이력을 수집한다 | P1 |
| FR-REC-006 | 사용자별 카테고리 선호도를 추론한다 | P2 |
| FR-REC-007 | 시간대별 활동 패턴을 수집한다 | P2 |
| FR-REC-008 | 수집 시 DB 성능에 영향을 주지 않아야 한다 (write-behind) | P0 |

## 3.2 수집 이벤트 정의

```
EventType:
  SEARCH              ← 검색 실행
  PRODUCT_VIEW        ← 상품 상세 조회
  CATEGORY_VIEW       ← 카테고리 페이지 조회
  CART_ADD            ← 장바구니 추가
  CART_REMOVE         ← 장바구니 제거
  WISHLIST_ADD        ← 찜 추가
  WISHLIST_REMOVE     ← 찜 제거
  VOTE_HOT            ← 핫딜 투표 (HOT)
  VOTE_NOT            ← 핫딜 투표 (NOT)
  HOTDEAL_VIEW        ← 핫딜 상세 조회
  HOTDEAL_CLICK       ← 핫딜 외부 링크 클릭
  PRICE_ALERT_SET     ← 가격 알림 설정
  PAGE_VIEW           ← 페이지 진입 (메인, 마트, 커뮤니티 등)
```

## 3.3 데이터 모델

### ⚠️ 성능 핵심: 별도 analytics 테이블 (메인 테이블 오염 방지)

### 신규 테이블: `user_events` (원시 이벤트)

```python
class UserEvent(Base):
    """사용자 행동 이벤트 원시 로그 — analytics 전용, 메인 쿼리에서 JOIN하지 않음"""
    __tablename__ = "user_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    # NULL이면 비로그인 사용자 (session_id로 추적)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # SEARCH, PRODUCT_VIEW, CART_ADD, ...

    # 이벤트 컨텍스트 (이벤트 타입에 따라 다른 필드 사용)
    product_id: Mapped[Optional[int]] = mapped_column(Integer)
    category_id: Mapped[Optional[str]] = mapped_column(String(100))
    search_query: Mapped[Optional[str]] = mapped_column(String(200))
    source: Mapped[Optional[str]] = mapped_column(String(50))
    # "emart", "homeplus", "ppomppu", "search_result", ...
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    # 추가 컨텍스트: {"deal_price": 2900, "position": 3, "page": "home"}

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_events_user_type", "user_id", "event_type"),
        Index("ix_events_created", "created_at"),
        Index("ix_events_user_created", "user_id", "created_at"),
        Index("ix_events_session", "session_id"),
        # 파티셔닝 힌트: PostgreSQL에서 created_at 기준 월별 파티션 적용
    )
```

### 신규 테이블: `user_category_scores` (집계 테이블)

```python
class UserCategoryScore(Base):
    """사용자별 카테고리 선호 점수 — 배치로 집계, 추천 시 직접 조회"""
    __tablename__ = "user_category_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    # 가중합: search=1, view=2, cart_add=5, wishlist=4, vote_hot=3
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    last_interaction: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("user_id", "category_id", name="uq_user_category_score"),
        Index("ix_cat_score_user", "user_id"),
        Index("ix_cat_score_category", "category_id"),
    )
```

### 신규 테이블: `user_activity_daily` (일별 활동 집계)

```python
class UserActivityDaily(Base):
    """일별 활동 집계 — 시간대 패턴 분석용"""
    __tablename__ = "user_activity_daily"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    # "2025-07-16"
    hour_distribution: Mapped[Optional[dict]] = mapped_column(JSON)
    # {"8": 3, "12": 5, "19": 8} — 시간대별 이벤트 수
    event_counts: Mapped[Optional[dict]] = mapped_column(JSON)
    # {"SEARCH": 5, "PRODUCT_VIEW": 12, "CART_ADD": 2}
    top_categories: Mapped[Optional[list]] = mapped_column(JSON)
    # ["meat.pork", "vegetable.root"]
    total_events: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_user_activity_date"),
        Index("ix_activity_daily_user", "user_id"),
        Index("ix_activity_daily_date", "date"),
    )
```

## 3.4 성능 설계 (⚠️ 핵심)

### 3.4.1 Write-Behind 캐싱 (배치 쓰기)

```
아키텍처:

  [프론트엔드]
      ↓ POST /api/events/batch (5~10개 묶어서)
  [백엔드 API]
      ↓
  [인메모리 이벤트 버퍼] ← collections.deque(maxlen=10000)
      ↓ (5초마다 or 버퍼 500개 이상 시)
  [배치 INSERT 워커] ← asyncio.create_task() or threading.Timer
      ↓ executemany()
  [user_events 테이블]
      ↓ (15분마다 scheduled job)
  [집계 워커]
      ↓ GROUP BY user_id, category_id → UPSERT
  [user_category_scores 테이블]
  [user_activity_daily 테이블]
```

### 3.4.2 Rate Limiting

```
규칙:
  - 동일 user_id + 동일 event_type: 최소 3초 간격
  - 동일 user_id + PRODUCT_VIEW + 동일 product_id: 최소 30초 간격
  - 동일 session_id: 최대 100 이벤트/분
  - 비로그인 사용자: 최대 30 이벤트/분

구현:
  - 인메모리 dict: {(user_id, event_type, target_id): last_timestamp}
  - TTL 60초 (자동 정리)
  - Redis 전환 시: SETEX 키로 대체
```

### 3.4.3 집계 전략

```
1. 카테고리 점수 가중치:
   SEARCH          = 1.0
   PRODUCT_VIEW    = 2.0
   CATEGORY_VIEW   = 1.5
   CART_ADD         = 5.0
   CART_REMOVE      = -2.0
   WISHLIST_ADD     = 4.0
   WISHLIST_REMOVE  = -1.5
   VOTE_HOT         = 3.0
   VOTE_NOT         = -1.0
   HOTDEAL_CLICK    = 3.5
   PRICE_ALERT_SET  = 4.5

2. 시간 감쇠 (time decay):
   score = weight × e^(-λ × days_since_event)
   λ = 0.05 (반감기 ≈ 14일)

3. 집계 주기:
   - user_category_scores: 15분마다 (최근 1시간 이벤트 기준 증분 업데이트)
   - user_activity_daily: 자정 배치 (전일 데이터 전체 집계)
```

### 3.4.4 데이터 보존 정책

```
user_events:       90일 보존 → 이후 집계 테이블로 요약 후 삭제
user_category_scores: 영구 보존 (사용자당 최대 50개 카테고리)
user_activity_daily:  365일 보존 → 이후 월별 요약으로 압축
```

## 3.5 API 엔드포인트

### POST `/api/events/batch`

클라이언트에서 배치 전송.

```
Authorization: Bearer <JWT> (optional — 비로그인 시 session_id만)

Body:
{
  "session_id": "abc123def456",
  "events": [
    {
      "event_type": "PRODUCT_VIEW",
      "product_id": 42,
      "category_id": "meat.pork.belly",
      "source": "search_result",
      "metadata": {"position": 3, "page": "price"},
      "client_timestamp": "2025-07-16T14:30:00Z"
    },
    {
      "event_type": "SEARCH",
      "search_query": "삼겹살",
      "metadata": {"result_count": 15},
      "client_timestamp": "2025-07-16T14:29:55Z"
    }
  ]
}

Response 202: { "success": true, "accepted": 2, "dropped": 0 }
  (202 Accepted — 즉시 처리 보장하지 않음)

Error 429: 이벤트 전송 한도 초과
```

### GET `/api/users/me/recommendations` (향후 사용)

```
Authorization: Bearer <JWT>

Query: ?limit=10&context=home

Response 200:
{
  "success": true,
  "data": {
    "recommended_products": [...],
    "recommended_categories": [...],
    "personalized_hotdeals": [...],
    "reasoning": "최근 삼겹살, 양파를 자주 검색하셨습니다"
  }
}
```

## 3.6 프론트엔드 이벤트 수집

```
hooks/useEventTracker.js:

  const tracker = useEventTracker()

  // 자동 수집 (컴포넌트 마운트 시)
  tracker.trackPageView("home")
  tracker.trackProductView(productId, categoryId, source)

  // 명시적 수집 (사용자 액션 시)
  tracker.trackSearch(query, resultCount)
  tracker.trackCartAdd(productId, price, source)
  tracker.trackVote(postId, voteType)

내부 동작:
  1. 이벤트를 로컬 배열에 축적
  2. 5초마다 OR 배열 10개 이상 시 → POST /api/events/batch
  3. 페이지 언로드 시 → navigator.sendBeacon()으로 잔여 이벤트 전송
  4. 실패 시 localStorage에 저장 → 다음 세션에서 재전송
```

## 3.7 보안 고려사항

| 위협 | 대응 |
|------|------|
| 이벤트 스푸핑 (다른 사용자 ID) | JWT에서 user_id 추출, body의 user_id 무시 |
| 이벤트 폭주 (DoS) | Rate limiting (100/분/세션), 429 응답 |
| 개인정보 (검색 기록) | GDPR/개인정보보호법 준수: 탈퇴 시 user_events 삭제, 90일 자동 삭제 |
| 이벤트 데이터로 사용자 프로파일링 | 집계 테이블만 추천에 사용, 원시 로그는 분석팀 접근 제한 |

---

# 4. 마트 상품 상세 모달

## 4.1 현재 문제

마트 상품은 이름+가격만 표시되며 클릭 시 아무 반응 없음.  
`Product.attributes`가 0/1171건 채워져 있지 않아 단가(per 100g) 비교 불가.

## 4.2 기능 요구사항

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-MODAL-001 | 마트 상품 클릭 → 상세 모달 열기 | P0 |
| FR-MODAL-002 | 모달에 표시: 상품 이미지, 가격, 마트명, 단위가격(per 100g/개), 카테고리 | P0 |
| FR-MODAL-003 | 동일 상품 다른 마트 가격 비교 (cross-mart comparison) | P0 |
| FR-MODAL-004 | 가격 이력 차트 (데이터 있을 때) | P1 |
| FR-MODAL-005 | "시세 대비" 표시 — 3단계 전략 (아래 참조) | P1 |
| FR-MODAL-006 | 모달에서 장바구니 추가, 찜 추가, 공유 버튼 | P1 |
| FR-MODAL-007 | 관련 핫딜 표시 (같은 상품의 온라인 핫딜) | P2 |

### "시세 대비" 3단계 비교 전략

```
1단계 — 정부 기준가 비교 (표준 품목):
  조건: product.category_id가 KAMIS 매핑 카테고리에 존재
  대상: 삼겹살, 양파, 배추, 쌀, 달걀 등 KAMIS 품목
  비교: product.price vs baseline_prices(source="kamis").latest_price
  표시: "도매가 대비 +12%" / "소매 평균가 대비 -8%"

2단계 — 자체 크롤링 데이터 카테고리 평균 비교 (브랜드 상품):
  조건: KAMIS 매핑 없지만, 같은 category_id의 다른 상품이 5건 이상
  대상: "비비드키친 저당 발사믹드레싱", "CJ 비건 프로틴 초코" 등
  비교: product.price vs AVG(discount_history.price WHERE category_id = same)
  표시: "카테고리 평균 대비 -15%"

3단계 — 비교 데이터 없음:
  조건: 위 두 가지 모두 불가
  대상: 신상품, 니치 상품
  표시: "비교 데이터 없음 — 데이터 수집 중입니다"
  추가: 다른 마트 가격 있으면 그것만이라도 표시
```

## 4.3 API 엔드포인트

### GET `/api/products/{id}/detail-modal`

모달에 필요한 모든 정보를 한 번에 반환.

```
Response 200:
{
  "success": true,
  "data": {
    "product": {
      "id": 42,
      "name": "삼겹살 (국내산) 100g",
      "image_url": "https://cdn.emart.com/...",
      "category_id": "meat.pork.belly",
      "category_name": "축산물 > 돼지고기 > 삼겹살",
      "unit": "100g",
      "attributes": {
        "weight_g": 100,
        "origin": "국내산",
        "storage": "냉장"
      }
    },

    "current_prices": [
      {
        "source": "emart",
        "source_name": "이마트",
        "price": 1890,
        "original_price": 2390,
        "discount_rate": 20.9,
        "unit_price_per_100g": 1890,
        "source_url": "https://emart.ssg.com/...",
        "valid_from": "2025-07-14",
        "valid_to": "2025-07-20",
        "crawled_at": "2025-07-16T06:00:00Z"
      },
      {
        "source": "homeplus",
        "source_name": "홈플러스",
        "price": 2190,
        "original_price": null,
        "discount_rate": null,
        "unit_price_per_100g": 2190,
        "source_url": "https://www.homeplus.co.kr/...",
        "valid_from": null,
        "valid_to": null,
        "crawled_at": "2025-07-16T05:30:00Z"
      }
    ],

    "price_comparison": {
      "strategy": "kamis_baseline",
      "strategy_label": "도매가 대비",
      "baseline_price": 1650,
      "baseline_source": "KAMIS 도매시세",
      "baseline_date": "2025-07-15",
      "vs_baseline_percent": 14.5,
      "tier": "good",
      "tier_label": "적정가"
    },
    /* OR */
    "price_comparison": {
      "strategy": "category_average",
      "strategy_label": "카테고리 평균 대비",
      "category_avg_price": 3200,
      "sample_count": 15,
      "vs_avg_percent": -9.4,
      "tier": "great",
      "tier_label": "할인 중"
    },
    /* OR */
    "price_comparison": {
      "strategy": "no_data",
      "strategy_label": "비교 데이터 없음",
      "message": "이 상품의 시세 데이터를 수집 중입니다"
    },

    "price_history": {
      "available": true,
      "period": "30d",
      "data_points": [
        {"date": "2025-06-16", "price": 2390, "source": "emart"},
        {"date": "2025-06-23", "price": 2190, "source": "emart"},
        {"date": "2025-06-30", "price": 1890, "source": "emart"}
      ],
      "min_price": 1690,
      "max_price": 2590,
      "avg_price": 2100
    },

    "related_hotdeals": [
      {
        "id": 5,
        "title": "[쿠팡] 삼겹살 1kg 국내산 특가",
        "price": 16900,
        "source": "coupang",
        "votes_hot": 45,
        "votes_not": 3
      }
    ],

    "user_state": {
      "is_in_cart": false,
      "is_in_wishlist": true,
      "wishlist_id": 7,
      "price_alert": {
        "id": 3,
        "target_price": 1500,
        "is_active": true
      }
    }
  }
}
```

### GET `/api/products/{id}/cross-mart`

동일 상품의 마트 간 가격 비교 (상세 모달 내 서브 요청).

```
Response 200:
{
  "success": true,
  "data": {
    "product_name": "삼겹살 (국내산) 100g",
    "matches": [
      {
        "source": "emart",
        "matched_name": "이마트 국내산 삼겹살 100g",
        "match_confidence": 0.95,
        "price": 1890,
        "crawled_at": "2025-07-16T06:00:00Z"
      },
      {
        "source": "homeplus",
        "matched_name": "홈플러스 국산 삼겹살 (냉장) 100g",
        "match_confidence": 0.88,
        "price": 2190,
        "crawled_at": "2025-07-16T05:30:00Z"
      },
      {
        "source": "lottemart",
        "matched_name": "롯데마트 삼겹살 국내산 100g",
        "match_confidence": 0.91,
        "price": 2050,
        "crawled_at": "2025-07-16T04:00:00Z"
      }
    ],
    "cheapest": "emart",
    "price_range": {"min": 1890, "max": 2190, "diff_percent": 15.9}
  }
}
```

## 4.4 프론트엔드 컴포넌트

```
components/ProductDetailModal/
├── ProductDetailModal.jsx        ← 메인 모달 컨테이너
├── ProductDetailModal.module.css
├── sections/
│   ├── ProductHeader.jsx         ← 이미지 + 상품명 + 카테고리
│   ├── PriceComparisonTable.jsx  ← 마트별 가격 비교 테이블
│   ├── PriceVsBaseline.jsx       ← "시세 대비" 배지 (3단계 전략)
│   ├── PriceHistoryChart.jsx     ← 가격 이력 AreaChart (Recharts)
│   ├── RelatedHotdeals.jsx       ← 관련 핫딜 리스트
│   └── ActionButtons.jsx         ← 장바구니/찜/공유/알림 버튼
└── hooks/
    └── useProductDetail.js       ← 모달 데이터 fetch + 캐시
```

**모달 상태 관리:**

```
productModalStore:
  isOpen: boolean
  productId: number | null
  productData: ProductDetail | null
  isLoading: boolean
  error: string | null
  actions:
    openModal(productId: number)
    closeModal()
    fetchDetail(productId)
```

## 4.5 엣지 케이스

1. `image_url` NULL → 카테고리별 기본 플레이스홀더 이미지 (`meat_placeholder.svg`)
2. `attributes` NULL → 단위가격 계산 불가 → "단위가격 정보 없음" 표시
3. 마트 1곳에만 있는 상품 → "다른 마트 가격 정보가 없습니다" + "알림 설정하기" 유도
4. 가격 이력 3일 미만 → 차트 대신 텍스트 표시 ("충분한 이력이 없습니다")
5. 모달 열린 상태에서 URL 공유 → deep link 지원 (`/marts?product=42&modal=true`)
6. cross-mart 매칭 confidence < 0.7 → "유사 상품 (정확도 낮음)" 라벨
7. `price_comparison.strategy = "no_data"` → 회색 톤 UI + "데이터 수집 중" 메시지

---

# 5. 카테고리 자동 분류 개선

## 5.1 현재 문제 분석

```
문제: 삼겹살을 검색하면 Homeplus만 나오고 Emart/Lottemart는 안 나옴.

근본 원인:
  1. 1171개 상품 중 24개만 category_id 할당됨 (2%)
  2. 각 마트 크롤러가 다른 상품명 형식 사용:
     - Emart: "[행사]냉장 국내산 삼겹살 구이용 100g"
     - Homeplus: "삼겹살(냉장) 100g 국산"
     - Lottemart: "국내산 냉장 삼겹살 100g"
  3. 자동 분류기가 이 변형들을 같은 카테고리로 매핑 못함
  4. Product 마스터에 정규화된 이름과 원본 이름이 혼재
```

## 5.2 기능 요구사항

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-CAT-001 | 상품명 정규화 파이프라인 — 크롤링 시점에 원본명 + 정규화명 둘 다 저장 | P0 |
| FR-CAT-002 | 한국어 식품명 퍼지 매칭 (형태소 분석 기반) | P0 |
| FR-CAT-003 | 마트 간 동일 상품 매칭 (cross-mart matching) | P0 |
| FR-CAT-004 | category_id 자동 할당 (신뢰도 0.8 이상 자동, 미만 대기열) | P0 |
| FR-CAT-005 | attributes 자동 추출 (무게, 원산지, 보관방법) | P1 |
| FR-CAT-006 | 관리자 보정 피드백 루프 (CategoryCorrection 활용) | P1 |

## 5.3 정규화 파이프라인 설계

### 5.3.1 상품명 정규화 단계

```
입력: "[행사]냉장 국내산 삼겹살 구이용 100g"

Step 1 — 노이즈 제거:
  정규식으로 제거: [행사], [특가], [핫딜], [MD추천], [농할 20%쿠폰 상세 다운]
  결과: "냉장 국내산 삼겹살 구이용 100g"

Step 2 — 속성 추출:
  무게 패턴: (\d+)(g|kg|ml|L|개|입|팩|봉)
  → weight: "100g", weight_g: 100
  원산지 패턴: (국내산|국산|수입산|미국산|호주산|칠레산|...)
  → origin: "국내산"
  보관 패턴: (냉장|냉동|상온|실온)
  → storage: "냉장"
  용도 패턴: (구이용|탕용|찌개용|볶음용|...)
  → usage: "구이용"
  결과: attributes = {weight_g: 100, origin: "국내산", storage: "냉장", usage: "구이용"}

Step 3 — 핵심 상품명 추출:
  속성 제거 후 남은 핵심 토큰: "삼겹살"
  결과: normalized_name = "삼겹살"

Step 4 — 동의어 매핑:
  토큰 매핑 테이블:
    "삼겹" → "삼겹살"
    "삼겹 살" → "삼겹살"
    "pork belly" → "삼겹살"
    "목심" → "목살"
    "목살" → "목살"
  결과: canonical_name = "삼겹살"
```

### 5.3.2 카테고리 매핑

```
canonical_name → category_id 매핑 전략:

1. 정확 매치 (keywords 테이블):
   "삼겹살" → category_id = "meat.pork.belly" (신뢰도 1.0)

2. 토큰 매치 (parsed_keywords):
   토큰 ["삼겹살", "국내산", "냉장"]
   → "삼겹살" in keywords → meat.pork.belly (신뢰도 0.95)

3. 퍼지 매치 (jamo 분해 + Levenshtein):
   "삼겹살구이" → "삼겹살" (edit distance 2) → meat.pork.belly (신뢰도 0.80)

4. 카테고리 추론 (상위 카테고리 키워드):
   토큰에 "돼지" 포함 → meat.pork (신뢰도 0.60) → 대기열
```

### 5.3.3 Cross-Mart 상품 매칭

```
목표: "이마트 삼겹살 100g"과 "홈플러스 삼겹살 100g"이 같은 Product 마스터를 참조

매칭 기준:
  1. canonical_name 일치 (필수)
  2. weight_g 일치 또는 ±10% 범위 (선택)
  3. origin 일치 (선택, 가점)
  4. storage 일치 (선택, 가점)

매칭 결과:
  - confidence ≥ 0.85 → 자동 매칭 (같은 product_id 할당)
  - 0.70 ≤ confidence < 0.85 → 후보 제시 (관리자 확인)
  - confidence < 0.70 → 별도 Product 레코드 유지

데이터 모델:
  DiscountHistory.product_id가 같은 Product를 가리키면
  → cross-mart 비교가 자연스럽게 동작
```

## 5.4 데이터 모델 변경

### Product 모델 확장

```python
# Product 모델에 추가:
raw_name: Mapped[Optional[str]] = mapped_column(String(500))
# 크롤링 원본 이름 보존
normalized_name: Mapped[Optional[str]] = mapped_column(String(200))
# 정규화된 이름 ("삼겹살")
canonical_name: Mapped[Optional[str]] = mapped_column(String(100))
# 동의어 매핑 후 표준명

# 인덱스 추가
Index("ix_products_normalized", "normalized_name")
Index("ix_products_canonical", "canonical_name")
```

### 신규 테이블: `product_name_synonyms`

```python
class ProductNameSynonym(Base):
    """상품명 동의어 사전"""
    __tablename__ = "product_name_synonyms"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # "삼겹살"
    variant: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    # "삼겹", "삼겹 살", "pork belly", "三枚肉"
    source: Mapped[str] = mapped_column(String(20), default="manual")
    # "manual" | "auto" | "correction"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

### 신규 테이블: `cross_mart_matches`

```python
class CrossMartMatch(Base):
    """마트 간 동일 상품 매칭 결과"""
    __tablename__ = "cross_mart_matches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    matched_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    match_reason: Mapped[Optional[str]] = mapped_column(String(200))
    # "canonical_name_exact + weight_match + origin_match"
    status: Mapped[str] = mapped_column(String(20), default="auto")
    # "auto" | "confirmed" | "rejected"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("product_id", "matched_product_id", name="uq_cross_match"),
        Index("ix_cross_match_product", "product_id"),
        Index("ix_cross_match_confidence", "confidence"),
    )
```

## 5.5 마이그레이션 전략

```
Phase 1 — 스키마 준비:
  1. Product에 raw_name, normalized_name, canonical_name 컬럼 추가
  2. product_name_synonyms, cross_mart_matches 테이블 생성
  3. 기존 product.name → raw_name으로 복사 (백업)

Phase 2 — 동의어 사전 초기화:
  1. KAMIS 품목 목록에서 기본 동의어 사전 생성 (약 200개 식품)
  2. 기존 keywords 테이블의 synonyms 필드 → product_name_synonyms로 이관
  3. 관리자가 수동 추가/보정

Phase 3 — 기존 데이터 재분류:
  1. 1171개 상품에 정규화 파이프라인 일괄 실행
  2. confidence ≥ 0.8 → 자동 category_id 할당
  3. 0.5 ≤ confidence < 0.8 → PendingCategorization 대기열
  4. confidence < 0.5 → 미분류 유지 + 관리자 알림

Phase 4 — 크롤러 연동:
  1. 크롤러 → db-admin ingestion 파이프라인에 정규화 단계 삽입
  2. 새 크롤링 데이터는 자동으로 정규화 + 분류
  3. 기존 Product 매칭 시 cross_mart_matches 자동 생성
```

---

# 6. 주유소 정보 개선

## 6.1 현행 상태

```
현재:
  - GasStation 테이블: 8건 샘플 데이터 (서울 일부)
  - GET /api/gas/nearby: haversine 거리 계산 (앱 레벨)
  - source: "opinet" (하드코딩)
  - 실시간 Opinet API 연동 여부: 미확인 (샘플 데이터만 존재)
  - 프론트엔드 LocalPage.jsx에서 표시: 평균 휘발유/경유 가격
  - 지도: Naver Map iframe으로 위치 표시
```

## 6.2 기능 요구사항

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-GAS-001 | Opinet API에서 실시간 주유소 가격 데이터 수집 (배치) | P0 |
| FR-GAS-002 | 사용자 위치 기준 반경 내 주유소 가격 비교 정렬 | P0 |
| FR-GAS-003 | 연료 유형 필터 (휘발유, 경유, LPG) | P0 |
| FR-GAS-004 | 가격 이력/추세 표시 (최근 7일) | P1 |
| FR-GAS-005 | 셀프/일반 주유소 필터 | P1 |
| FR-GAS-006 | 브랜드 필터 (SK, GS, 현대, S-OIL, 기타) | P2 |
| FR-GAS-007 | 지도에 주유소 마커 + 가격 표시 | P1 |
| FR-GAS-008 | "최저가 주유소" 하이라이트 | P1 |

## 6.3 Opinet API 연동 설계

```
Opinet API (공공데이터):
  - 주유소 목록: GET /api/avgAllPrice.do (전국 평균 유가)
  - 주변 주유소: GET /api/aroundAll.do?x=...&y=...&radius=...&sort=1
  - 가격 이력: GET /api/avgRecentPrice.do (최근 1주 평균)
  - API Key: 공공데이터포털 발급 필요 (환경변수 OPINET_API_KEY)

데이터 수집 전략:
  1. 스케줄 배치 (1시간마다):
     - 전국 평균 유가 → gas_price_national 테이블
     - 주요 도시별 평균 → gas_price_regional 테이블

  2. 온디맨드 (사용자 요청 시):
     - /api/gas/nearby → 캐시 확인(10분 TTL) → 미스 시 Opinet aroundAll 호출
     - 결과 gas_stations 테이블 UPSERT + 캐시 저장

  3. 일별 배치 (자정):
     - 가격 이력 스냅샷 → gas_price_history 테이블
```

## 6.4 데이터 모델

### GasStation 모델 확장

```python
# GasStation 모델에 추가:
opinet_id: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
# Opinet 고유 ID — UPSERT 키
premium_gasoline_price: Mapped[Optional[float]] = mapped_column(Float)
# 고급 휘발유
car_wash: Mapped[bool] = mapped_column(Boolean, default=False)
convenience_store: Mapped[bool] = mapped_column(Boolean, default=False)
operating_hours: Mapped[Optional[str]] = mapped_column(String(100))
# "06:00-23:00" 또는 "24시간"

# 인덱스 추가
Index("ix_gas_opinet_id", "opinet_id")
Index("ix_gas_brand", "brand")
```

### 신규 테이블: `gas_price_history`

```python
class GasPriceHistory(Base):
    """주유소 가격 이력 — 일별 스냅샷"""
    __tablename__ = "gas_price_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(
        ForeignKey("gas_stations.id", ondelete="CASCADE"), nullable=False
    )
    gasoline_price: Mapped[Optional[float]] = mapped_column(Float)
    diesel_price: Mapped[Optional[float]] = mapped_column(Float)
    lpg_price: Mapped[Optional[float]] = mapped_column(Float)
    premium_gasoline_price: Mapped[Optional[float]] = mapped_column(Float)
    recorded_date: Mapped[str] = mapped_column(String(10), nullable=False)
    # "2025-07-16"
    source: Mapped[str] = mapped_column(String(20), default="opinet")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("station_id", "recorded_date", name="uq_gas_history_date"),
        Index("ix_gas_history_station", "station_id"),
        Index("ix_gas_history_date", "recorded_date"),
    )
```

## 6.5 API 엔드포인트 개선

### GET `/api/gas/nearby` (확장)

```
Query Parameters:
  lat: 37.5665 (required)
  lng: 126.9780 (required)
  radius: 3 (km, default: 3, max: 10)
  fuel_type: "gasoline" | "diesel" | "lpg" | "premium" (default: "gasoline")
  sort: "price" | "distance" (default: "price")
  brand: "SK,GS,현대" (optional, comma-separated)
  is_self: true | false (optional)
  page: 1
  per_page: 20

Response 200:
{
  "success": true,
  "data": {
    "stations": [
      {
        "id": 1,
        "opinet_id": "A0001234",
        "name": "강남 셀프 SK 주유소",
        "brand": "SK",
        "address": "서울시 강남구 역삼동 123-4",
        "lat": 37.5012,
        "lng": 127.0396,
        "distance_km": 0.8,
        "is_self": true,
        "gasoline_price": 1645,
        "diesel_price": 1520,
        "lpg_price": 980,
        "premium_gasoline_price": 1845,
        "selected_fuel_price": 1645,
        "vs_avg_percent": -2.3,
        "is_cheapest": true,
        "updated_at": "2025-07-16T14:00:00Z"
      }
    ],
    "area_average": {
      "gasoline": 1683,
      "diesel": 1545,
      "lpg": 1010
    },
    "national_average": {
      "gasoline": 1695,
      "diesel": 1560,
      "lpg": 1025
    },
    "pagination": { "page": 1, "per_page": 20, "total": 12 }
  }
}
```

### GET `/api/gas/{station_id}/history`

```
Query: ?days=7&fuel_type=gasoline

Response 200:
{
  "success": true,
  "data": {
    "station_name": "강남 셀프 SK 주유소",
    "fuel_type": "gasoline",
    "history": [
      {"date": "2025-07-10", "price": 1670},
      {"date": "2025-07-11", "price": 1665},
      {"date": "2025-07-12", "price": 1660},
      {"date": "2025-07-13", "price": 1650},
      {"date": "2025-07-14", "price": 1645},
      {"date": "2025-07-15", "price": 1645},
      {"date": "2025-07-16", "price": 1645}
    ],
    "trend": "down",
    "change_7d": -25,
    "change_7d_percent": -1.5
  }
}
```

## 6.6 프론트엔드 컴포넌트

```
pages/Local/ (기존 LocalPage 확장)
├── GasStationPanel.jsx           ← 주유소 전용 패널 (독립 섹션)
├── GasStationList.jsx            ← 주유소 리스트 (정렬/필터)
├── GasStationCard.jsx            ← 개별 주유소 카드
├── GasStationMap.jsx             ← 지도 + 마커 표시
├── GasFuelTypeFilter.jsx         ← 연료 유형 탭 (휘발유/경유/LPG)
├── GasBrandFilter.jsx            ← 브랜드 체크박스 필터
├── GasPriceHistoryChart.jsx      ← 가격 추세 차트
└── GasAreaAverage.jsx            ← 지역/전국 평균 가격 비교
```

## 6.7 엣지 케이스

1. Opinet API 장애 → 캐시된 최신 데이터 + "마지막 업데이트: 2시간 전" 경고
2. 사용자 위치 권한 거부 → 기본 지역(서울) 또는 수동 주소 입력
3. 반경 내 주유소 0건 → 반경 자동 확대 제안 (3km → 5km)
4. LPG 가격 없는 주유소 → 해당 필터 시 제외 + "LPG 미취급" 표시
5. 가격 0원 or 비정상 가격 → 필터링 (gasoline 1000~3000 범위 외 제외)

---

# 7. 홈 → 상품 네비게이션

## 7.1 현재 문제

```
문제:
  홈페이지 "이번 주 마트 할인" 섹션에서 특정 상품(예: "삼겹살 1890원") 클릭 시
  → /marts 페이지로 이동하지만 해당 상품의 상세 모달은 열리지 않음
  → 사용자가 마트 목록에서 다시 찾아야 함

원인:
  - 홈페이지에서 navigate('/marts') 만 호출
  - URL에 상품 ID/모달 상태가 포함되지 않음
  - MartPage가 URL 파라미터에서 상품 ID를 읽지 않음
```

## 7.2 기능 요구사항

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-NAV-001 | 홈 → 마트 상품 클릭 → `/marts?product=42&modal=true` → MartPage에서 해당 상품 모달 자동 열기 | P0 |
| FR-NAV-002 | 홈 → 핫딜 클릭 → `/hotdeals?id=5&modal=true` → HotdealPage에서 해당 핫딜 모달 자동 열기 | P0 |
| FR-NAV-003 | 홈 → 커뮤니티 글 클릭 → `/community?post=10&modal=true` → CommunityPage에서 해당 글 모달 자동 열기 | P1 |
| FR-NAV-004 | Deep link 공유 가능 (URL 복사 → 붙여넣기 → 동일 상태 재현) | P0 |
| FR-NAV-005 | 모달 닫기 시 URL에서 쿼리 파라미터 제거 (히스토리 정리) | P1 |
| FR-NAV-006 | 브라우저 뒤로가기 → 모달 닫힘 (popstate 핸들링) | P1 |

## 7.3 URL 상태 관리 설계

```
URL 패턴:

/marts                                → 마트 목록 (기본)
/marts?store=emart                    → 이마트 탭 선택
/marts?store=emart&product=42         → 이마트 탭 + 상품 42 하이라이트
/marts?store=emart&product=42&modal=true  → 이마트 탭 + 상품 42 모달 열기

/hotdeals                             → 핫딜 목록
/hotdeals?category=food               → 식품 카테고리 필터
/hotdeals?id=5&modal=true             → 핫딜 5번 모달 열기

/community                            → 커뮤니티
/community?type=hotdeal               → 핫딜 게시판
/community?post=10&modal=true         → 게시글 10번 모달 열기

/price?id=42                          → 상품 42 가격 페이지 (기존)
/price/category/meat.pork.belly       → 카테고리 비교 (기존)
```

## 7.4 프론트엔드 구현 설계

### 공통 훅: `useModalNavigation`

```
hooks/useModalNavigation.js:

  기능:
    1. URL searchParams에서 모달 상태 읽기
    2. 모달 열기 → URL에 파라미터 추가 (history.pushState)
    3. 모달 닫기 → URL에서 파라미터 제거 (history.replaceState)
    4. 브라우저 뒤로가기 → popstate 이벤트 → 모달 닫기
    5. 페이지 로드 시 URL에 modal=true → 자동 모달 열기

  인터페이스:
    const { isModalOpen, targetId, openModal, closeModal } = useModalNavigation({
      paramName: "product",   // URL 파라미터명
      modalParam: "modal"     // 모달 열기 파라미터명
    })
```

### 홈페이지 수정 사항

```
현재:
  onClick={() => navigate('/marts')}

변경:
  onClick={() => navigate(`/marts?store=${store}&product=${productId}&modal=true`)}

적용 대상:
  - "이번 주 마트 할인" 섹션의 각 상품 카드
  - "인기 핫딜" 섹션의 각 핫딜 카드
  - "최근 게시글" 섹션의 각 게시글 카드
  - "오늘의 물가" 섹션의 카테고리 항목
```

### 각 페이지 수정 사항

```
MartPage.jsx:
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const productId = params.get("product")
    const showModal = params.get("modal") === "true"
    const store = params.get("store")

    if (store) setActiveStore(store)
    if (productId && showModal) {
      openProductDetailModal(parseInt(productId))
    }
  }, [location.search])

HotdealPage.jsx:
  (동일 패턴 — id + modal 파라미터)

CommunityPage.jsx:
  (동일 패턴 — post + modal 파라미터)
```

## 7.5 엣지 케이스

1. Deep link의 상품이 삭제됨 → "상품을 찾을 수 없습니다" 토스트 + 모달 미표시
2. 비로그인 상태에서 찜/장바구니 버튼 클릭 → 로그인 페이지 리다이렉트 + 원래 URL 보존
3. 모달 안에서 다른 상품 클릭 (관련 상품) → URL 갱신 + 모달 내용 교체 (새 모달 아님)
4. 매우 느린 네트워크에서 모달 데이터 로드 → 스켈레톤 UI 표시
5. 같은 URL에서 새로고침 → 동일 모달 상태 복원 (SSR 불필요, CSR 충분)
6. popstate 이벤트 시 모달이 이미 닫혀있는 경우 → 이중 실행 방지

---

# 8. DB 성능 설계

## 8.1 현행 문제

```
현재 아키텍처:
  - SQLite 단일 파일 (development)
  - website + db-admin이 같은 DB 파일 직접 접근 (sys.path 해킹)
  - TTLCache 인메모리 (프로세스 로컬, 재시작 시 소멸)
  - Rate limiting: 인메모리 dict
  - 페이지네이션: estimate 기반 (total = page * per_page + 1)
  - Connection pooling: SQLAlchemy 기본값 (pool_size=5)

동시 사용자 시나리오:
  - 50명 동시 접속 (최소 목표)
  - 500명 동시 접속 (중기 목표)
  - 초당 100 읽기 + 10 쓰기 (피크 시)
```

## 8.2 Connection Pooling 전략

```
현재 (SQLite):
  - SQLAlchemy StaticPool (단일 연결) 또는 NullPool
  - 동시 쓰기 불가 (WAL 모드에서도 1 writer)

Phase 1 — SQLite WAL + 읽기 최적화:
  engine = create_engine(
      "sqlite:///walletdb.sqlite",
      connect_args={"check_same_thread": False},
      pool_size=1,
      max_overflow=0,
  )
  # WAL 모드 활성화
  @event.listens_for(engine, "connect")
  def set_sqlite_pragma(dbapi_conn, record):
      cursor = dbapi_conn.cursor()
      cursor.execute("PRAGMA journal_mode=WAL")
      cursor.execute("PRAGMA busy_timeout=5000")
      cursor.execute("PRAGMA synchronous=NORMAL")
      cursor.execute("PRAGMA cache_size=-64000")  # 64MB 캐시
      cursor.execute("PRAGMA temp_store=MEMORY")
      cursor.close()

Phase 2 — PostgreSQL 전환:
  engine = create_engine(
      DATABASE_URL,   # postgresql://...
      pool_size=20,
      max_overflow=10,
      pool_timeout=30,
      pool_recycle=1800,
      pool_pre_ping=True,
  )

Phase 3 — 읽기 전용 레플리카 (향후):
  read_engine = create_engine(READ_REPLICA_URL, ...)
  write_engine = create_engine(PRIMARY_URL, ...)
  # 라우팅: SELECT → read_engine, INSERT/UPDATE/DELETE → write_engine
```

## 8.3 캐싱 레이어 설계

### 3-Tier 캐시 아키텍처

```
Tier 1 — 프로세스 로컬 (TTLCache):
  용도: 극도로 빈번한 읽기, 변경 거의 없는 데이터
  대상:
    - 카테고리 목록 (TTL: 10분)
    - 마트 목록 (TTL: 30분)
    - 핫딜 소스 목록 (TTL: 30분)
    - 트렌딩 키워드 (TTL: 5분)
  구현: cachetools.TTLCache (현행 유지)
  용량: 최대 1000 항목

Tier 2 — 공유 캐시 (Redis):
  용도: 다중 프로세스/인스턴스 공유 데이터
  대상:
    - 주유소 가격 (TTL: 10분)
    - 상품 검색 결과 (TTL: 3분, 키: query hash)
    - 대시보드 데이터 (TTL: 5분)
    - 세션 데이터 (TTL: 24시간)
    - Rate limit 카운터 (TTL: 60초)
  구현: redis-py + aioredis
  구조:
    cache:product:{id}             → JSON
    cache:search:{query_hash}      → JSON
    cache:gas:nearby:{lat}:{lng}   → JSON
    ratelimit:{user_id}:{action}   → counter
    session:{session_id}           → JSON

Tier 3 — DB 쿼리 결과 캐시 (SQLAlchemy 레벨):
  용도: 복잡한 집계 쿼리 결과
  대상:
    - category-summary (TTL: 15분)
    - category-compare (TTL: 15분)
    - 가격 통계 (TTL: 10분)
  구현: 커스텀 데코레이터 + Redis
```

### 캐시 무효화 전략

```
전략: Event-Driven Invalidation

1. 크롤러 데이터 입수 시:
   → cache:product:* 패턴 삭제
   → cache:search:* 패턴 삭제
   → cache:gas:* 패턴 삭제 (주유소 크롤 시)

2. 사용자 액션 시:
   → 장바구니 변경 → cache:cart:{user_id} 삭제
   → 투표/댓글 → cache:post:{post_id} 삭제

3. TTL 기반 자동 만료:
   → 대부분 데이터 3~15분 TTL
   → 카테고리/마트 목록 10~30분 TTL

4. 수동 무효화 API (관리자):
   → POST /api/admin/cache/flush?pattern=...
```

## 8.4 Write Batching (분석 데이터)

```
대상: user_events 테이블 (Section 3 참조)

배치 쓰기 파이프라인:

  [API 요청]
      ↓ (즉시)
  [인메모리 이벤트 큐] — collections.deque(maxlen=10000)
      ↓
  [배치 INSERT 스레드] — 5초 간격 OR 큐 500건 이상
      ↓ session.execute(insert(UserEvent), batch_list)
  [user_events 테이블]

  최적화:
    - executemany() 사용 (개별 INSERT 대비 10x 빠름)
    - 배치 크기: 500건 (메모리 vs 지연 트레이드오프)
    - 실패 시: 로컬 파일에 JSON 덤프 → 다음 주기에 재시도
    - 큐 가득 참: 오래된 이벤트 드롭 (deque maxlen 활용)

  모니터링 메트릭:
    - queue_size: 현재 큐 대기 건수
    - batch_write_latency: 배치 INSERT 소요 시간
    - events_dropped: 큐 오버플로우로 버려진 이벤트 수
    - events_written: 성공적으로 DB에 쓴 이벤트 수
```

## 8.5 페이지네이션

```
현재 문제:
  total = page * per_page + 1  ← 항상 "다음 페이지 있음"으로 추정 (가짜)

개선 설계:

1. Offset-based (기본):
   - COUNT(*) 쿼리로 정확한 total 제공
   - COUNT 쿼리 결과 캐시 (TTL: 30초)
   - 단점: 페이지 수 많으면 느림

   SELECT COUNT(*) FROM products WHERE category_id = 'meat.pork';
   SELECT * FROM products WHERE category_id = 'meat.pork'
     ORDER BY id LIMIT 20 OFFSET 40;

2. Cursor-based (대량 데이터):
   - user_events, discount_history 등 데이터 많은 테이블
   - last_id 기반 커서

   SELECT * FROM user_events
     WHERE user_id = 1 AND id > :last_id
     ORDER BY id
     LIMIT 20;

   응답:
   {
     "items": [...],
     "cursor": {
       "next": "eyJpZCI6IDEyMzQ1fQ==",  // base64({"id": 12345})
       "has_next": true
     }
   }

3. 적용 기준:
   - 상품 목록, 게시글, 핫딜: offset-based (사용자가 "N페이지" 이동)
   - 이벤트 로그, 가격 이력: cursor-based (대량 순차 탐색)
   - 검색 결과: offset-based + total 캐시
```

## 8.6 쿼리 최적화 가이드라인

### 현재 문제 쿼리 & 개선

```
1. 카테고리 요약 (category-summary) — 현재 깨져있음

   현재:
     products = search_products()  # 전체 상품 로드
     grouped = {}
     for p in products:
         cat = p.get("category", "etc")  # ← category 키 없음 → 전부 "etc"

   개선:
     SELECT
       c.id AS category_id,
       c.name AS category_name,
       COUNT(p.id) AS product_count,
       AVG(dh.price) AS avg_price,
       MIN(dh.price) AS min_price
     FROM products p
     JOIN categories c ON p.category_id = c.id
     LEFT JOIN discount_history dh
       ON dh.product_id = p.id
       AND dh.crawled_at >= datetime('now', '-7 days')
     WHERE p.is_active = 1
       AND p.category_id IS NOT NULL
     GROUP BY c.id, c.name
     ORDER BY c.sort_order;

   인덱스 필요:
     - ix_products_category (기존)
     - ix_discount_product_date (기존)


2. Cross-mart 가격 비교

   SELECT
     p.name,
     dh.source,
     dh.price,
     dh.original_price,
     dh.discount_rate,
     dh.crawled_at
   FROM discount_history dh
   JOIN products p ON dh.product_id = p.id
   WHERE p.canonical_name = :canonical_name
     AND dh.crawled_at >= datetime('now', '-7 days')
   ORDER BY dh.source, dh.crawled_at DESC;

   인덱스 필요:
     - ix_products_canonical (신규)
     - ix_discount_product_source (기존)


3. 사용자 피드 (대시보드)

   -- 기존: 8개 개별 API 호출
   -- 개선: /api/dashboard 엔드포인트 활용 (이미 존재하지만 프론트에서 안 씀)

   구현 변경:
     HomePage.jsx에서 /api/dashboard 사용하도록 수정
     개별 API 호출 제거
```

### 인덱스 전략

```
원칙:
  1. 자주 쓰는 WHERE + ORDER BY 조합에 복합 인덱스
  2. JOIN에 사용되는 FK는 반드시 인덱스 (SQLAlchemy FK는 자동 아님)
  3. 부분 인덱스 활용 (PostgreSQL): WHERE is_active = true
  4. JSON 필드 인덱스: PostgreSQL GIN 인덱스 (SQLite 불가)

필수 신규 인덱스:
  - products.canonical_name (cross-mart 매칭)
  - products.normalized_name (정규화 검색)
  - cart_items(user_id, product_id) (장바구니 중복 체크)
  - user_events(user_id, event_type, created_at) (이벤트 집계)
  - gas_price_history(station_id, recorded_date) (이력 조회)
```

## 8.7 성능 요구사항

| 메트릭 | 목표값 | 측정 방법 |
|--------|--------|-----------|
| API 응답 시간 (P95) | ≤ 500ms | 캐시 히트 시 ≤ 100ms |
| 상품 검색 | ≤ 300ms | LIKE 쿼리 + 인덱스 |
| 대시보드 로딩 | ≤ 1000ms | 단일 /api/dashboard 호출 |
| 주유소 조회 | ≤ 500ms | 캐시 미스 시 Opinet + DB 저장 포함 |
| 이벤트 수집 | ≤ 50ms | 202 Accepted (비동기 처리) |
| 장바구니 CRUD | ≤ 200ms | 사용자별 인덱스 |
| DB 동시 연결 | 30 (Phase 1 SQLite) | WAL 모드 |
| DB 동시 연결 | 200 (Phase 2 PostgreSQL) | Connection pool |
| 캐시 히트율 | ≥ 80% | 카테고리, 마트, 트렌딩 등 |

---

# 부록 A: 전체 마이그레이션 로드맵

```
Week 1 — 스키마 & 기반:
  □ Alembic 마이그레이션 생성:
    - user_preferences 테이블
    - email_verifications 테이블
    - cart_items 테이블
    - user_events 테이블
    - user_category_scores 테이블
    - user_activity_daily 테이블
    - gas_price_history 테이블
    - product_name_synonyms 테이블
    - cross_mart_matches 테이블
  □ User 모델 확장 필드 추가
  □ Product 모델 확장 필드 추가
  □ Favorite 모델 확장 필드 추가
  □ GasStation 모델 확장 필드 추가

Week 2 — 백엔드 API:
  □ /api/users/me/profile (GET, PUT)
  □ /api/users/me/password (PUT)
  □ /api/users/me/email-change (POST)
  □ /api/users/me/cart (CRUD)
  □ /api/events/batch (POST)
  □ /api/products/{id}/detail-modal (GET)
  □ /api/products/{id}/cross-mart (GET)
  □ /api/gas/nearby 확장
  □ /api/gas/{id}/history (GET)

Week 3 — 분류 & 데이터:
  □ 상품명 정규화 파이프라인 구현
  □ 동의어 사전 초기화 (KAMIS 기반)
  □ 기존 1171개 상품 재분류 배치
  □ Cross-mart 매칭 배치 실행
  □ Opinet API 연동 + 배치 수집
  □ Write-behind 이벤트 버퍼 구현

Week 4 — 프론트엔드:
  □ ProfilePage 신규 (탭 구조)
  □ CartDrawer + CartIcon
  □ ProductDetailModal
  □ useModalNavigation 훅
  □ HomePage 네비게이션 수정
  □ MartPage URL 파라미터 핸들링
  □ useEventTracker 훅
  □ GasStationPanel 개선

Week 5 — 통합 & 성능:
  □ /api/dashboard를 HomePage에서 실제 사용
  □ 캐시 레이어 적용 (TTLCache 정리 + Redis 준비)
  □ 페이지네이션 정확한 total 구현
  □ 이벤트 집계 배치 job 구현
  □ 통합 테스트
  □ 성능 벤치마크 (k6 or locust)
```

---

# 부록 B: 보안 체크리스트

| # | 항목 | 적용 범위 | 상태 |
|---|------|-----------|------|
| 1 | 모든 사용자 데이터 API에 JWT 인증 필수 | cart, profile, favorites, events | 신규 |
| 2 | CORS 허용 도메인 제한 | 전체 API | 기존 확인 필요 |
| 3 | 이미지 업로드 malware 스캔 (최소 magic bytes 검증) | profile image | 신규 |
| 4 | 비밀번호 정책 (최소 8자, 영+숫자+특수문자) | password change | 신규 |
| 5 | Rate limiting (인메모리 → Redis 전환) | events/batch, auth/login | 개선 |
| 6 | SQL Injection 방지 (ORM 파라미터 바인딩 확인) | 전체 쿼리 | 기존 확인 필요 |
| 7 | XSS 방지 (사용자 입력 HTML escape) | nickname, post, comment | 기존 확인 필요 |
| 8 | CSRF 토큰 (쿠키 기반 인증 사용 시) | auth endpoints | 기존 확인 필요 |
| 9 | 개인정보 삭제 요청 처리 (GDPR) | account deletion, events purge | 신규 |
| 10 | 감사 로그 (AuditLog 테이블 실제 활용) | admin actions, data changes | 개선 |
| 11 | 서비스 간 통신 인증 (crawler → db-admin) | ingestion API | 기존 미구현 |
| 12 | source_url 화이트리스트 | cart items, hotdeal links | 신규 |

---

# 부록 C: 용어 사전

| 한글 | 영문 | 설명 |
|------|------|------|
| 시세 대비 | vs. market price | 현재 가격 대 기준가(도매가/카테고리 평균) 비율 |
| 적정가 | fair price | 시세 대비 85~105% 구간 |
| 초특가 | ultra deal | 시세 대비 70% 이하 |
| 찜 | wishlist | 가격 추적 목적의 관심 상품 목록 |
| 장바구니 | cart | 구매 의향 상품 모음 (비교/정리용) |
| 정규화명 | normalized name | 크롤링 원본에서 노이즈 제거 후 상품명 |
| 표준명 | canonical name | 동의어 매핑 완료된 최종 상품명 |
| Write-behind | write-behind cache | 쓰기를 메모리에 버퍼링 후 일괄 DB 반영 |
| 배치 쓰기 | batch write | 다수 레코드를 한 번에 INSERT |

---

> **문서 끝** — 이 문서는 설계 명세서이며, 구현 코드를 포함하지 않습니다.  
> 각 섹션의 데이터 모델은 기존 `models.py` 스타일(SQLAlchemy 2.0 Mapped 문법)을 따릅니다.  
> API 엔드포인트의 Request/Response 스키마는 기존 `ApiResponse(success, data)` 패턴을 따릅니다.
