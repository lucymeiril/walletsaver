# DB Admin — Input Validation, Error Handling & Data Protection

> **Generated**: 2025-07-19
> **Source Audits**: `db-admin-code-audit.md` (Issues 4-6, 11-14, 21-22), `db-admin-arch-audit.md` (Issues 8-9, 13)
> **Scope**: `packages/db-admin/backend/`
> **Tracks**: Code-Audit Issues #4, #5, #6, #11, #12, #14, #21; Arch-Audit Issues #8, #9, #13

---

## Table of Contents

1. [Shared Utility Module](#1-shared-utility-module)
2. [Input Validation — Pydantic Models](#2-input-validation--pydantic-models)
3. [LIKE Pattern Injection Fix](#3-like-pattern-injection-fix)
4. [Dynamic getattr() Safety](#4-dynamic-getattr-safety)
5. [Error Handling — Global + Per-Route](#5-error-handling--global--per-route)
6. [Payload Size Limits](#6-payload-size-limits)
7. [Audit Logging](#7-audit-logging)
8. [Test Cases](#8-test-cases)

---

## 1. Shared Utility Module

### New file: `backend/api/security.py`

This module centralizes LIKE escaping, error response schemas, and the standard error response builder.

```python
"""Shared security utilities for input sanitization and error responses."""
from __future__ import annotations

import re
import uuid
import logging
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("security")


# ── LIKE Pattern Escaping ──────────────────────────────────────────────

def escape_like(value: str) -> str:
    """Escape SQL LIKE special characters (%, _, \\).

    Use with SQLAlchemy .ilike() / .like():
        Model.col.ilike(f"%{escape_like(user_input)}%")
    """
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


# ── Standard Error Response Schema ─────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str            # machine-readable, e.g. "VALIDATION_ERROR"
    message: str         # human-readable, safe for client display
    request_id: str      # trace ID for log correlation


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ── Error Response Builder ─────────────────────────────────────────────

_ERROR_MESSAGES = {
    "VALIDATION_ERROR":    "입력 데이터가 올바르지 않습니다.",
    "NOT_FOUND":           "요청한 리소스를 찾을 수 없습니다.",
    "CONFLICT":            "이미 존재하는 리소스입니다.",
    "CONFIRM_MISMATCH":    "확인 문자열이 올바르지 않습니다.",
    "PAYLOAD_TOO_LARGE":   "요청 본문이 너무 큽니다.",
    "INTERNAL_ERROR":      "서버 내부 오류가 발생했습니다.",
    "INVALID_SORT_FIELD":  "허용되지 않는 정렬 필드입니다.",
    "INVALID_TABLE":       "허용되지 않는 테이블입니다.",
    "INVALID_FIELD":       "허용되지 않는 필드입니다.",
    "BULK_LIMIT_EXCEEDED": "벌크 작업 항목 수가 한도를 초과했습니다.",
}


def make_error(code: str, status_code: int = 400, detail_override: str | None = None) -> dict:
    """Build a standard error dict for HTTPException.

    Usage:
        raise HTTPException(**make_error("CONFIRM_MISMATCH"))
    """
    request_id = uuid.uuid4().hex[:12]
    message = detail_override or _ERROR_MESSAGES.get(code, "오류가 발생했습니다.")
    return {
        "status_code": status_code,
        "detail": {
            "code": code,
            "message": message,
            "request_id": request_id,
        },
    }


# ── Input Constraints (constants) ──────────────────────────────────────

MAX_BULK_IDS = 500
MAX_INGESTION_ITEMS = 10_000
MAX_INGESTION_ERRORS = 1_000
MAX_BULK_PRICE_ITEMS = 5_000
MAX_SYNONYM_COUNT = 20
MAX_VALIDATE_ITEMS = 10_000
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MB

# String length limits (aligned with DB column sizes)
MAX_NAME_LEN = 255
MAX_CATEGORY_ID_LEN = 100
MAX_UNIT_LEN = 50
MAX_DESCRIPTION_LEN = 5_000
MAX_URL_LEN = 2_048
MAX_KEYWORD_LEN = 100
MAX_ICON_LEN = 50
MAX_SOURCE_LEN = 100
MAX_NOTES_LEN = 2_000
MAX_REASON_LEN = 2_000
MAX_CRAWLER_NAME_LEN = 100
MAX_STRATEGY_LEN = 200
MAX_REVIEW_ACTION_VALUES = {"approve", "reject", "partial"}
MAX_CLEANUP_STATUS_VALUES = {"approved", "rejected", "pending", "crawler_approved", "partial"}
ALLOWED_SCHEMA_TYPES = {"DiscountItem", "HotdealPost", "BaselineItem"}
ALLOWED_CRAWL_STATUSES = {"success", "partial", "failed"}
ALLOWED_DATA_TYPES = {"baseline", "discount"}
```

---

## 2. Input Validation — Pydantic Models

Every Pydantic request model is hardened with `Field(...)` constraints, `field_validator`, and `model_validator`. Below are the exact replacements per file.

### 2.1 `backend/api/routes/products.py` — Lines 23-45

**Current code:**
```python
class ProductCreate(BaseModel):
    name: str
    category_id: Optional[str] = None
    unit: str = "개"
    description: Optional[str] = None
    image_url: Optional[str] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class BulkDeleteRequest(BaseModel):
    ids: list[int]

class BulkCategoryRequest(BaseModel):
    ids: list[int]
    category_id: str
```

**Replace with:**
```python
from pydantic import BaseModel, Field, field_validator
from api.security import (
    MAX_NAME_LEN, MAX_CATEGORY_ID_LEN, MAX_UNIT_LEN,
    MAX_DESCRIPTION_LEN, MAX_URL_LEN, MAX_BULK_IDS,
)


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)
    category_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)
    unit: str = Field("개", min_length=1, max_length=MAX_UNIT_LEN)
    description: Optional[str] = Field(None, max_length=MAX_DESCRIPTION_LEN)
    image_url: Optional[str] = Field(None, max_length=MAX_URL_LEN)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("상품명은 공백만으로 구성될 수 없습니다.")
        return v.strip()

    @field_validator("image_url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("URL은 http:// 또는 https://로 시작해야 합니다.")
        return v


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_NAME_LEN)
    category_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)
    unit: Optional[str] = Field(None, min_length=1, max_length=MAX_UNIT_LEN)
    description: Optional[str] = Field(None, max_length=MAX_DESCRIPTION_LEN)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("상품명은 공백만으로 구성될 수 없습니다.")
        return v.strip() if v else v


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=MAX_BULK_IDS)


class BulkCategoryRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=MAX_BULK_IDS)
    category_id: str = Field(..., min_length=1, max_length=MAX_CATEGORY_ID_LEN)
```

### 2.2 `backend/api/routes/categories.py` — Lines 21-39

**Current code:**
```python
class CategoryCreate(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    icon: Optional[str] = None
    attributes: Optional[dict] = None
    sort_order: int = 0

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    attributes: Optional[dict] = None
    is_active: Optional[bool] = None

class CategoryMove(BaseModel):
    new_parent_id: Optional[str] = None
```

**Replace with:**
```python
import re
from pydantic import BaseModel, Field, field_validator
from api.security import MAX_CATEGORY_ID_LEN, MAX_NAME_LEN, MAX_ICON_LEN

_CATEGORY_ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9]+)*$")


class CategoryCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=MAX_CATEGORY_ID_LEN)
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)
    parent_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)
    icon: Optional[str] = Field(None, max_length=MAX_ICON_LEN)
    attributes: Optional[dict] = None
    sort_order: int = Field(0, ge=0, le=9999)

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        if not _CATEGORY_ID_RE.match(v):
            raise ValueError(
                "카테고리 ID는 소문자 영숫자와 점(.)으로 구성해야 합니다. (예: meat.pork.belly)"
            )
        return v


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_NAME_LEN)
    icon: Optional[str] = Field(None, max_length=MAX_ICON_LEN)
    sort_order: Optional[int] = Field(None, ge=0, le=9999)
    attributes: Optional[dict] = None
    is_active: Optional[bool] = None


class CategoryMove(BaseModel):
    new_parent_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)
```

### 2.3 `backend/api/routes/keywords.py` — Lines 23-37

**Current code:**
```python
class KeywordCreate(BaseModel):
    word: str
    synonyms: Optional[list[str]] = None
    category_id: Optional[str] = None

class KeywordUpdate(BaseModel):
    word: Optional[str] = None
    synonyms: Optional[list[str]] = None
    category_id: Optional[str] = None
    is_active: Optional[bool] = None

class BulkDeleteRequest(BaseModel):
    ids: Optional[list[int]] = None
```

**Replace with:**
```python
from pydantic import BaseModel, Field, field_validator
from api.security import (
    MAX_KEYWORD_LEN, MAX_CATEGORY_ID_LEN, MAX_SYNONYM_COUNT, MAX_BULK_IDS,
)


class KeywordCreate(BaseModel):
    word: str = Field(..., min_length=1, max_length=MAX_KEYWORD_LEN)
    synonyms: Optional[list[str]] = Field(None, max_length=MAX_SYNONYM_COUNT)
    category_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)

    @field_validator("word")
    @classmethod
    def word_stripped(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("키워드는 공백만으로 구성될 수 없습니다.")
        return v

    @field_validator("synonyms")
    @classmethod
    def validate_synonyms(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned = []
        for s in v:
            s = s.strip()
            if not s:
                continue
            if len(s) > MAX_KEYWORD_LEN:
                raise ValueError(f"동의어는 {MAX_KEYWORD_LEN}자를 초과할 수 없습니다.")
            cleaned.append(s)
        return cleaned


class KeywordUpdate(BaseModel):
    word: Optional[str] = Field(None, min_length=1, max_length=MAX_KEYWORD_LEN)
    synonyms: Optional[list[str]] = Field(None, max_length=MAX_SYNONYM_COUNT)
    category_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)
    is_active: Optional[bool] = None


class BulkDeleteRequest(BaseModel):
    ids: Optional[list[int]] = Field(None, max_length=MAX_BULK_IDS)
```

### 2.4 `backend/api/routes/ingestion.py` — Lines 33-61

**Current code:**
```python
class IngestionSubmit(BaseModel):
    crawler_name: str
    crawl_status: str = "success"
    items: list[dict] = []
    schema_type: str = "DiscountItem"
    strategy_used: Optional[str] = None
    duration_seconds: Optional[float] = None
    errors: list[dict] = []
    source_url: Optional[str] = None

class ReviewRequest(BaseModel):
    action: str
    notes: Optional[str] = None
    approved_item_indices: Optional[list[int]] = None
    rejected_reason: Optional[str] = None

class BulkApproveRequest(BaseModel):
    ids: list[int]
    reviewer: Optional[str] = None
    notes: Optional[str] = None

class CleanupRequest(BaseModel):
    status: list[str] = ["approved", "rejected"]
    older_than_days: Optional[int] = None
    confirm: bool = False
```

**Replace with:**
```python
from pydantic import BaseModel, Field, field_validator
from api.security import (
    MAX_INGESTION_ITEMS, MAX_INGESTION_ERRORS, MAX_CRAWLER_NAME_LEN,
    MAX_STRATEGY_LEN, MAX_URL_LEN, MAX_NOTES_LEN, MAX_REASON_LEN,
    MAX_BULK_IDS, ALLOWED_SCHEMA_TYPES, ALLOWED_CRAWL_STATUSES,
    MAX_REVIEW_ACTION_VALUES, MAX_CLEANUP_STATUS_VALUES,
)


class IngestionSubmit(BaseModel):
    crawler_name: str = Field(..., min_length=1, max_length=MAX_CRAWLER_NAME_LEN)
    crawl_status: str = Field("success", max_length=20)
    items: list[dict] = Field(default_factory=list, max_length=MAX_INGESTION_ITEMS)
    schema_type: str = Field("DiscountItem", max_length=50)
    strategy_used: Optional[str] = Field(None, max_length=MAX_STRATEGY_LEN)
    duration_seconds: Optional[float] = Field(None, ge=0, le=86_400)
    errors: list[dict] = Field(default_factory=list, max_length=MAX_INGESTION_ERRORS)
    source_url: Optional[str] = Field(None, max_length=MAX_URL_LEN)

    @field_validator("crawl_status")
    @classmethod
    def validate_crawl_status(cls, v: str) -> str:
        if v not in ALLOWED_CRAWL_STATUSES:
            raise ValueError(f"crawl_status는 {ALLOWED_CRAWL_STATUSES} 중 하나여야 합니다.")
        return v

    @field_validator("schema_type")
    @classmethod
    def validate_schema_type(cls, v: str) -> str:
        if v not in ALLOWED_SCHEMA_TYPES:
            raise ValueError(f"schema_type은 {ALLOWED_SCHEMA_TYPES} 중 하나여야 합니다.")
        return v

    @field_validator("source_url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("URL은 http:// 또는 https://로 시작해야 합니다.")
        return v


class ReviewRequest(BaseModel):
    action: str = Field(..., max_length=20)
    notes: Optional[str] = Field(None, max_length=MAX_NOTES_LEN)
    approved_item_indices: Optional[list[int]] = Field(None, max_length=MAX_INGESTION_ITEMS)
    rejected_reason: Optional[str] = Field(None, max_length=MAX_REASON_LEN)

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in MAX_REVIEW_ACTION_VALUES:
            raise ValueError(f"action은 {MAX_REVIEW_ACTION_VALUES} 중 하나여야 합니다.")
        return v


class BulkApproveRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=MAX_BULK_IDS)
    reviewer: Optional[str] = Field(None, max_length=MAX_NAME_LEN)
    notes: Optional[str] = Field(None, max_length=MAX_NOTES_LEN)


class CleanupRequest(BaseModel):
    status: list[str] = Field(
        default=["approved", "rejected"],
        min_length=1,
        max_length=5,
    )
    older_than_days: Optional[int] = Field(None, ge=1, le=3650)
    confirm: bool = False

    @field_validator("status")
    @classmethod
    def validate_status_values(cls, v: list[str]) -> list[str]:
        invalid = set(v) - MAX_CLEANUP_STATUS_VALUES
        if invalid:
            raise ValueError(f"허용되지 않는 status 값: {invalid}")
        return v
```

### 2.5 `backend/api/routes/prices.py` — Lines 120-134

**Current code:**
```python
class PriceItem(BaseModel):
    product_id: int
    price: float
    source: str
    unit: str = "개"
    region: Optional[str] = None

class BulkPriceRequest(BaseModel):
    items: list[PriceItem]
    data_type: str = "baseline"

class TierConfigRequest(BaseModel):
    tiers: dict
```

**Replace with:**
```python
from pydantic import BaseModel, Field, field_validator
from api.security import (
    MAX_BULK_PRICE_ITEMS, MAX_SOURCE_LEN, MAX_UNIT_LEN,
    ALLOWED_DATA_TYPES,
)

ALLOWED_TIER_KEYS = {"ultra", "great", "good", "wait", "bad"}


class PriceItem(BaseModel):
    product_id: int = Field(..., gt=0)
    price: float = Field(..., gt=0, le=100_000_000)
    source: str = Field(..., min_length=1, max_length=MAX_SOURCE_LEN)
    unit: str = Field("개", min_length=1, max_length=MAX_UNIT_LEN)
    region: Optional[str] = Field(None, max_length=100)


class BulkPriceRequest(BaseModel):
    items: list[PriceItem] = Field(..., min_length=1, max_length=MAX_BULK_PRICE_ITEMS)
    data_type: str = Field("baseline", max_length=20)

    @field_validator("data_type")
    @classmethod
    def validate_data_type(cls, v: str) -> str:
        if v not in ALLOWED_DATA_TYPES:
            raise ValueError(f"data_type은 {ALLOWED_DATA_TYPES} 중 하나여야 합니다.")
        return v


class TierConfigRequest(BaseModel):
    tiers: dict

    @field_validator("tiers")
    @classmethod
    def validate_tier_keys(cls, v: dict) -> dict:
        invalid_keys = set(v.keys()) - ALLOWED_TIER_KEYS
        if invalid_keys:
            raise ValueError(f"허용되지 않는 티어 키: {invalid_keys}")
        for key, tier in v.items():
            if not isinstance(tier, dict):
                raise ValueError(f"'{key}' 티어 값은 dict여야 합니다.")
            if "label" not in tier:
                raise ValueError(f"'{key}' 티어에 'label' 필드가 필요합니다.")
            threshold = tier.get("threshold")
            if threshold is not None and not isinstance(threshold, (int, float)):
                raise ValueError(f"'{key}' threshold는 숫자 또는 null이어야 합니다.")
        return v
```

### 2.6 `backend/api/routes/analytics.py` — Lines 50-61

**Current code:**
```python
class DuplicateRequest(BaseModel):
    table_name: str
    fields: list[str]

class ValidateRequest(BaseModel):
    items: list[dict]
```

**Replace with:**
```python
from pydantic import BaseModel, Field, field_validator
from api.security import MAX_VALIDATE_ITEMS

ALLOWED_DUPLICATE_FIELDS = {
    "products": {"name", "category_id"},
    "baseline_prices": {"product_id", "source", "price"},
    "discount_history": {"product_id", "source", "price"},
    "hotdeal_prices": {"product_id", "source", "price"},
    "categories": {"name", "parent_id"},
    "keywords": {"word"},
}
ALLOWED_TABLE_NAMES = set(ALLOWED_DUPLICATE_FIELDS.keys())


class DuplicateRequest(BaseModel):
    table_name: str = Field(..., max_length=50)
    fields: list[str] = Field(..., min_length=1, max_length=5)

    @field_validator("table_name")
    @classmethod
    def validate_table(cls, v: str) -> str:
        if v not in ALLOWED_TABLE_NAMES:
            raise ValueError(f"허용되지 않는 테이블: {v}")
        return v

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, v: list[str], info) -> list[str]:
        # Can only validate against table when both fields present
        return v


class ValidateRequest(BaseModel):
    items: list[dict] = Field(..., min_length=1, max_length=MAX_VALIDATE_ITEMS)
```

### 2.7 `backend/api/routes/admin.py` — Lines 26-36

**Current code:**
```python
class ResetSourceRequest(BaseModel):
    source: str
    confirm: str

class ResetProductsRequest(BaseModel):
    confirm: str

class ResetAllRequest(BaseModel):
    confirm: str
```

**Replace with:**
```python
from pydantic import BaseModel, Field
from api.security import MAX_SOURCE_LEN


class ResetSourceRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=MAX_SOURCE_LEN)
    confirm: str = Field(..., min_length=1, max_length=100)


class ResetProductsRequest(BaseModel):
    confirm: str = Field(..., min_length=1, max_length=100)


class ResetAllRequest(BaseModel):
    confirm: str = Field(..., min_length=1, max_length=100)
```

---

## 3. LIKE Pattern Injection Fix

**Addresses**: Code-Audit Issue #4, autocomplete service LIKE patterns

### 3.1 Affected Locations (7 total)

| # | File | Line | Current Code | Fixed Code |
|---|------|------|-------------|------------|
| 1 | `api/routes/keywords.py` | 58 | `Keyword.word.ilike(f"%{q}%")` | `Keyword.word.ilike(f"%{escape_like(q)}%")` |
| 2 | `api/routes/keywords.py` | 59 | `Keyword.synonyms.cast(SAString).ilike(f"%{q}%")` | `Keyword.synonyms.cast(SAString).ilike(f"%{escape_like(q)}%")` |
| 3 | `api/routes/prices.py` | 40 | `BaselinePrice.source.ilike(f"%{source}%")` | `BaselinePrice.source.ilike(f"%{escape_like(source)}%")` |
| 4 | `api/routes/prices.py` | 447 | `BaselinePrice.source.ilike(f"%{source}%")` | `BaselinePrice.source.ilike(f"%{escape_like(source)}%")` |
| 5 | `api/routes/prices.py` | 510 | `BaselinePrice.source.ilike(f"%{source}%")` | `BaselinePrice.source.ilike(f"%{escape_like(source)}%")` |
| 6 | `api/routes/analytics.py` | 394 | `Product.name.ilike(f"%{q}%")` | `Product.name.ilike(f"%{escape_like(q)}%")` |
| 7 | `services/autocomplete.py` | 59 | `Keyword.word.like(f"{query}%")` | `Keyword.word.like(f"{escape_like(query)}%")` |
| 8 | `services/autocomplete.py` | 202 | `Keyword.word.like(f"%{query}%")` | `Keyword.word.like(f"%{escape_like(query)}%")` |
| 9 | `services/autocomplete.py` | 213 | `Category.name.like(f"%{query}%")` | `Category.name.like(f"%{escape_like(query)}%")` |

### 3.2 Exact Changes

**File: `backend/api/routes/keywords.py`**

Add import at the top (after line 8):
```python
from api.security import escape_like
```

Change lines 57-60:
```python
# BEFORE
            or_(
                Keyword.word.ilike(f"%{q}%"),
                Keyword.synonyms.cast(SAString).ilike(f"%{q}%"),
            )

# AFTER
            or_(
                Keyword.word.ilike(f"%{escape_like(q)}%"),
                Keyword.synonyms.cast(SAString).ilike(f"%{escape_like(q)}%"),
            )
```

**File: `backend/api/routes/prices.py`**

Add import at the top (after line 8):
```python
from api.security import escape_like
```

Change line 40:
```python
# BEFORE
            conditions.append(BaselinePrice.source.ilike(f"%{source}%"))
# AFTER
            conditions.append(BaselinePrice.source.ilike(f"%{escape_like(source)}%"))
```

Change line 447 (same pattern):
```python
# BEFORE
            conditions.append(BaselinePrice.source.ilike(f"%{source}%"))
# AFTER
            conditions.append(BaselinePrice.source.ilike(f"%{escape_like(source)}%"))
```

Change line 510 (same pattern):
```python
# BEFORE
            conditions.append(BaselinePrice.source.ilike(f"%{source}%"))
# AFTER
            conditions.append(BaselinePrice.source.ilike(f"%{escape_like(source)}%"))
```

**File: `backend/api/routes/analytics.py`**

Add import at the top:
```python
from api.security import escape_like
```

Change line 394:
```python
# BEFORE
            .where(Product.is_active == True, Product.name.ilike(f"%{q}%"))
# AFTER
            .where(Product.is_active == True, Product.name.ilike(f"%{escape_like(q)}%"))
```

**File: `backend/services/autocomplete.py`**

Add import at the top:
```python
from api.security import escape_like
```

Change line 59:
```python
# BEFORE
            Keyword.word.like(f"{query}%"),
# AFTER
            Keyword.word.like(f"{escape_like(query)}%"),
```

Change line 202:
```python
# BEFORE
            Keyword.word.like(f"%{query}%"),
# AFTER
            Keyword.word.like(f"%{escape_like(query)}%"),
```

Change line 213:
```python
# BEFORE
                Category.name.like(f"%{query}%"),
# AFTER
                Category.name.like(f"%{escape_like(query)}%"),
```

---

## 4. Dynamic `getattr()` Safety

**Addresses**: Code-Audit Issues #5, #12

### 4.1 `backend/api/routes/keywords.py` — Line 69

**Current code:**
```python
sort_col = getattr(Keyword, sort_by, Keyword.search_count)
```

**Replace with:**
```python
ALLOWED_KEYWORD_SORT_FIELDS = {"word", "search_count", "is_active", "id", "category_id"}

# ... inside list_keywords():
if sort_by not in ALLOWED_KEYWORD_SORT_FIELDS:
    sort_by = "search_count"
sort_col = getattr(Keyword, sort_by)
```

Place the `ALLOWED_KEYWORD_SORT_FIELDS` constant at module level (e.g., after line 20).

### 4.2 `backend/services/data_quality.py` — Line 125

**Current code:**
```python
columns = [getattr(model, f) for f in fields if hasattr(model, f)]
```

**Replace with:**
```python
from api.security import make_error

ALLOWED_DUPLICATE_FIELDS = {
    "products": {"name", "category_id"},
    "baseline_prices": {"product_id", "source", "price"},
    "discount_history": {"product_id", "source", "price"},
    "hotdeal_prices": {"product_id", "source", "price"},
    "categories": {"name", "parent_id"},
    "keywords": {"word"},
}

def find_duplicates(session: Session, table_name: str, fields: list[str]) -> list[dict]:
    """중복 데이터 탐지"""
    model_map = {
        "products": Product,
        "baseline_prices": BaselinePrice,
        "discount_history": DiscountHistory,
        "hotdeal_prices": HotdealPrice,
        "categories": Category,
        "keywords": Keyword,
    }

    model = model_map.get(table_name)
    if not model:
        return []

    allowed = ALLOWED_DUPLICATE_FIELDS.get(table_name, set())
    validated_fields = [f for f in fields if f in allowed]
    if not validated_fields:
        return []

    columns = [getattr(model, f) for f in validated_fields]
    # ... rest unchanged ...
```

### 4.3 Add field validation in `analytics.py` duplicates endpoint

In `backend/api/routes/analytics.py`, add a validation step in the `duplicates()` handler (after line 74):

```python
@router.post("/duplicates")
def duplicates(body: DuplicateRequest):
    # Validate fields against allowlist
    allowed = ALLOWED_DUPLICATE_FIELDS.get(body.table_name)
    if allowed is None:
        raise HTTPException(**make_error("INVALID_TABLE"))
    invalid = set(body.fields) - allowed
    if invalid:
        raise HTTPException(**make_error("INVALID_FIELD"))

    session = get_session()
    try:
        return find_duplicates(session, body.table_name, body.fields)
    finally:
        session.close()
```

---

## 5. Error Handling — Global + Per-Route

**Addresses**: Code-Audit Issue #11

### 5.1 Global Exception Handler

**File: `backend/api/app.py`**

Add the following **after** the CORS middleware block and **before** router includes:

```python
import logging
import uuid
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

logger = logging.getLogger("api")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = uuid.uuid4().hex[:12]
    logger.warning(
        "Validation error [%s] %s %s: %s",
        request_id, request.method, request.url.path, exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "입력 데이터가 올바르지 않습니다.",
                "request_id": request_id,
                "details": [
                    {
                        "field": ".".join(str(loc) for loc in e["loc"]),
                        "message": e["msg"],
                    }
                    for e in exc.errors()
                ],
            }
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = uuid.uuid4().hex[:12]
    logger.error(
        "Unhandled error [%s] %s %s: %s",
        request_id, request.method, request.url.path, exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "서버 내부 오류가 발생했습니다.",
                "request_id": request_id,
            }
        },
    )
```

### 5.2 Admin Confirmation — Stop Leaking Expected Strings

**File: `backend/api/routes/admin.py`**

**Line 115-120 — reset-source** (current):
```python
    expected = f"DELETE_{body.source.upper()}"
    if body.confirm != expected:
        raise HTTPException(
            status_code=400,
            detail=f"확인 문자열이 올바르지 않습니다. '{expected}'를 입력하세요.",
        )
```

**Replace with:**
```python
    from api.security import make_error

    expected = f"DELETE_{body.source.upper()}"
    if body.confirm != expected:
        raise HTTPException(**make_error("CONFIRM_MISMATCH"))
```

**Line 173-177 — reset-products** (current):
```python
    if body.confirm != "DELETE_ALL_PRODUCTS":
        raise HTTPException(
            status_code=400,
            detail="확인 문자열이 올바르지 않습니다. 'DELETE_ALL_PRODUCTS'를 입력하세요.",
        )
```

**Replace with:**
```python
    from api.security import make_error

    if body.confirm != "DELETE_ALL_PRODUCTS":
        raise HTTPException(**make_error("CONFIRM_MISMATCH"))
```

**Line 226-230 — reset-all** (current):
```python
    if body.confirm != "RESET_ALL_DATA":
        raise HTTPException(
            status_code=400,
            detail="확인 문자열이 올바르지 않습니다. 'RESET_ALL_DATA'를 입력하세요.",
        )
```

**Replace with:**
```python
    from api.security import make_error

    if body.confirm != "RESET_ALL_DATA":
        raise HTTPException(**make_error("CONFIRM_MISMATCH"))
```

### 5.3 Replace `str(e)` Exposure

**File: `backend/api/routes/keywords.py` — Line 168**

Current:
```python
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
```

Replace with:
```python
        except ValueError:
            raise HTTPException(**make_error("VALIDATION_ERROR", 422))
```

### 5.4 Admin `except Exception: raise` — Add Error Wrapping

**File: `backend/api/routes/admin.py` — Lines 161-163, 214-216, 268-270**

All three admin endpoints have:
```python
    except Exception:
        session.rollback()
        raise
```

Replace each with:
```python
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        logger.error("Admin operation failed", exc_info=True)
        raise HTTPException(**make_error("INTERNAL_ERROR", 500))
```

This ensures the global handler catches any unhandled exception and the admin routes never leak raw SQLAlchemy or Python stack traces.

---

## 6. Payload Size Limits

**Addresses**: Code-Audit Issue #6, Arch-Audit Issue #8

### 6.1 Request Body Size Middleware

**File: `backend/api/app.py`** — Add after GZip middleware:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies larger than MAX_REQUEST_BODY_BYTES."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": f"요청 본문은 {MAX_REQUEST_BODY_BYTES // (1024*1024)}MB를 초과할 수 없습니다.",
                        "request_id": "",
                    }
                },
            )
        return await call_next(request)


# In create_app(), add BEFORE GZip:
app.add_middleware(RequestSizeLimitMiddleware)
```

### 6.2 Uvicorn Config Limit

**File: `backend/main.py`** — Add `--limit-max-request-size` in uvicorn.run:

```python
uvicorn.run(
    "api.app:create_app",
    host=settings.API_HOST,
    port=settings.API_PORT,
    reload=settings.DEBUG,
    limit_max_request_size=10 * 1024 * 1024,  # 10 MB
)
```

---

## 7. Audit Logging

**Addresses**: Arch-Audit Issue #9

### 7.1 Audit Log Model

**File: `backend/storage/models.py`** — Add at the end of the models file:

```python
class AuditLog(Base):
    """Append-only audit log for admin/write operations."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id = Column(String(100), nullable=True)      # placeholder until auth is implemented
    action = Column(String(50), nullable=False)        # CREATE, UPDATE, DELETE, BULK_DELETE, RESET, EXPORT, APPROVE
    entity_type = Column(String(50), nullable=False)   # product, category, keyword, price, ingestion
    entity_id = Column(String(255), nullable=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    request_id = Column(String(36), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_action", "action"),
    )
```

### 7.2 Audit Logger Service

**New file: `backend/services/audit.py`**

```python
"""Audit logging service — records all admin and write operations."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from storage.models import AuditLog

logger = logging.getLogger("audit")


def log_action(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    old_value: Any = None,
    new_value: Any = None,
    request: Request | None = None,
    user_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Insert an audit record. Call within the same DB session/transaction."""
    ip = None
    ua = None
    if request:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent", "")[:500]

    entry = AuditLog(
        timestamp=datetime.utcnow(),
        user_id=user_id or "anonymous",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_value=_safe_json(old_value),
        new_value=_safe_json(new_value),
        ip_address=ip,
        user_agent=ua,
        request_id=uuid.uuid4().hex[:12],
        metadata_=metadata,
    )
    session.add(entry)
    logger.info(
        "AUDIT | action=%s entity=%s/%s user=%s ip=%s",
        action, entity_type, entity_id, user_id or "anonymous", ip,
    )


def _safe_json(val: Any) -> Any:
    """Ensure value is JSON-serializable; truncate large values."""
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, dict):
        serialized = str(val)
        if len(serialized) > 10_000:
            return {"_truncated": True, "preview": serialized[:1000]}
        return val
    if isinstance(val, list):
        if len(val) > 100:
            return {"_truncated": True, "count": len(val), "sample": val[:5]}
        return val
    return str(val)[:1000]
```

### 7.3 Where to Add Audit Calls

Add `log_action()` calls in the following handlers. Each call should be placed **within the same `try` block**, right **before** `session.commit()`.

| File | Endpoint | Action | Entity Type |
|------|----------|--------|-------------|
| `routes/admin.py` | `POST /reset-source` | `RESET` | `source` |
| `routes/admin.py` | `POST /reset-products` | `RESET` | `products` |
| `routes/admin.py` | `POST /reset-all` | `RESET` | `all` |
| `routes/products.py` | `POST /` | `CREATE` | `product` |
| `routes/products.py` | `PUT /{id}` | `UPDATE` | `product` |
| `routes/products.py` | `DELETE /{id}` | `DELETE` | `product` |
| `routes/products.py` | `POST /bulk-delete` | `BULK_DELETE` | `product` |
| `routes/products.py` | `POST /bulk-category` | `BULK_UPDATE` | `product` |
| `routes/categories.py` | `POST /` | `CREATE` | `category` |
| `routes/categories.py` | `PUT /{id}` | `UPDATE` | `category` |
| `routes/categories.py` | `DELETE /{id}` | `DELETE` | `category` |
| `routes/keywords.py` | `POST /` | `CREATE` | `keyword` |
| `routes/keywords.py` | `PUT /{id}` | `UPDATE` | `keyword` |
| `routes/keywords.py` | `DELETE /{id}` | `DELETE` | `keyword` |
| `routes/keywords.py` | `POST /bulk-delete` | `BULK_DELETE` | `keyword` |
| `routes/prices.py` | `POST /bulk` | `BULK_CREATE` | `price` |
| `routes/prices.py` | `POST /tier-config` | `UPDATE` | `tier_config` |
| `routes/ingestion.py` | `POST /` | `CREATE` | `ingestion` |
| `routes/ingestion.py` | `POST /{id}/crawler-review` | `REVIEW` | `ingestion` |
| `routes/ingestion.py` | `POST /{id}/db-review` | `REVIEW` | `ingestion` |
| `routes/ingestion.py` | `POST /bulk-approve` | `BULK_APPROVE` | `ingestion` |
| `routes/ingestion.py` | `DELETE /{id}` | `DELETE` | `ingestion` |
| `routes/ingestion.py` | `POST /cleanup` | `CLEANUP` | `ingestion` |

**Example integration for `admin.py` reset-source** (add `request: Request` parameter):

```python
from fastapi import Request
from services.audit import log_action

@router.post("/reset-source")
def reset_source(body: ResetSourceRequest, request: Request):
    # ... confirm check ...
    session = get_session()
    try:
        # ... delete operations ...
        log_action(
            session,
            action="RESET",
            entity_type="source",
            entity_id=body.source,
            new_value={"discount_del": discount_del, "baseline_del": baseline_del, "hotdeal_del": hotdeal_del},
            request=request,
        )
        session.commit()
        # ...
```

**Example integration for `products.py` bulk-delete:**

```python
@router.post("/bulk-delete")
def bulk_delete(body: BulkDeleteRequest, request: Request):
    session = get_session()
    try:
        # ... delete logic ...
        log_action(
            session,
            action="BULK_DELETE",
            entity_type="product",
            metadata={"ids": body.ids, "count": len(body.ids)},
            request=request,
        )
        session.commit()
        # ...
```

### 7.4 Database Migration

Create an Alembic migration to add the `audit_log` table:

```bash
cd packages/db-admin/backend
alembic revision --autogenerate -m "add audit_log table"
alembic upgrade head
```

---

## 8. Test Cases

### 8.1 Test File: `backend/tests/test_input_validation.py`

```python
"""Input validation security tests."""
import pytest
from pydantic import ValidationError


class TestProductValidation:
    def test_name_too_long(self):
        from api.routes.products import ProductCreate
        with pytest.raises(ValidationError):
            ProductCreate(name="x" * 256)

    def test_name_blank(self):
        from api.routes.products import ProductCreate
        with pytest.raises(ValidationError):
            ProductCreate(name="   ")

    def test_name_min_length(self):
        from api.routes.products import ProductCreate
        with pytest.raises(ValidationError):
            ProductCreate(name="")

    def test_valid_product(self):
        from api.routes.products import ProductCreate
        p = ProductCreate(name="돼지고기 삼겹살", unit="100g")
        assert p.name == "돼지고기 삼겹살"

    def test_image_url_scheme(self):
        from api.routes.products import ProductCreate
        with pytest.raises(ValidationError):
            ProductCreate(name="test", image_url="javascript:alert(1)")

    def test_bulk_delete_too_many_ids(self):
        from api.routes.products import BulkDeleteRequest
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=list(range(501)))

    def test_bulk_delete_empty_ids(self):
        from api.routes.products import BulkDeleteRequest
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=[])


class TestCategoryValidation:
    def test_id_format_valid(self):
        from api.routes.categories import CategoryCreate
        c = CategoryCreate(id="meat.pork.belly", name="삼겹살")
        assert c.id == "meat.pork.belly"

    def test_id_format_invalid(self):
        from api.routes.categories import CategoryCreate
        with pytest.raises(ValidationError):
            CategoryCreate(id="MEAT/pork", name="돼지")

    def test_id_too_long(self):
        from api.routes.categories import CategoryCreate
        with pytest.raises(ValidationError):
            CategoryCreate(id="a" * 101, name="test")

    def test_sort_order_negative(self):
        from api.routes.categories import CategoryCreate
        with pytest.raises(ValidationError):
            CategoryCreate(id="test", name="test", sort_order=-1)


class TestKeywordValidation:
    def test_word_too_long(self):
        from api.routes.keywords import KeywordCreate
        with pytest.raises(ValidationError):
            KeywordCreate(word="x" * 101)

    def test_too_many_synonyms(self):
        from api.routes.keywords import KeywordCreate
        with pytest.raises(ValidationError):
            KeywordCreate(word="test", synonyms=["s"] * 21)

    def test_bulk_delete_limit(self):
        from api.routes.keywords import BulkDeleteRequest
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=list(range(501)))


class TestIngestionValidation:
    def test_too_many_items(self):
        from api.routes.ingestion import IngestionSubmit
        with pytest.raises(ValidationError):
            IngestionSubmit(
                crawler_name="test",
                items=[{"name": "x"}] * 10_001,
            )

    def test_invalid_schema_type(self):
        from api.routes.ingestion import IngestionSubmit
        with pytest.raises(ValidationError):
            IngestionSubmit(crawler_name="test", schema_type="EvilSchema")

    def test_invalid_crawl_status(self):
        from api.routes.ingestion import IngestionSubmit
        with pytest.raises(ValidationError):
            IngestionSubmit(crawler_name="test", crawl_status="hacked")

    def test_invalid_review_action(self):
        from api.routes.ingestion import ReviewRequest
        with pytest.raises(ValidationError):
            ReviewRequest(action="destroy")

    def test_cleanup_invalid_status(self):
        from api.routes.ingestion import CleanupRequest
        with pytest.raises(ValidationError):
            CleanupRequest(status=["invalid_status"], confirm=True)

    def test_valid_ingestion(self):
        from api.routes.ingestion import IngestionSubmit
        ing = IngestionSubmit(
            crawler_name="emart_crawler",
            items=[{"name": "apple", "sale_price": 1000}],
        )
        assert ing.crawler_name == "emart_crawler"
        assert len(ing.items) == 1


class TestPriceValidation:
    def test_price_must_be_positive(self):
        from api.routes.prices import PriceItem
        with pytest.raises(ValidationError):
            PriceItem(product_id=1, price=-100, source="test")

    def test_price_upper_limit(self):
        from api.routes.prices import PriceItem
        with pytest.raises(ValidationError):
            PriceItem(product_id=1, price=200_000_000, source="test")

    def test_bulk_too_many_items(self):
        from api.routes.prices import BulkPriceRequest, PriceItem
        items = [PriceItem(product_id=1, price=100, source="s")] * 5_001
        with pytest.raises(ValidationError):
            BulkPriceRequest(items=items)

    def test_invalid_data_type(self):
        from api.routes.prices import BulkPriceRequest, PriceItem
        items = [PriceItem(product_id=1, price=100, source="s")]
        with pytest.raises(ValidationError):
            BulkPriceRequest(items=items, data_type="evil")

    def test_tier_config_invalid_key(self):
        from api.routes.prices import TierConfigRequest
        with pytest.raises(ValidationError):
            TierConfigRequest(tiers={"hacker_tier": {"label": "x"}})


class TestAnalyticsValidation:
    def test_duplicate_invalid_table(self):
        from api.routes.analytics import DuplicateRequest
        with pytest.raises(ValidationError):
            DuplicateRequest(table_name="users", fields=["password"])

    def test_validate_too_many_items(self):
        from api.routes.analytics import ValidateRequest
        with pytest.raises(ValidationError):
            ValidateRequest(items=[{}] * 10_001)


class TestAdminValidation:
    def test_source_too_long(self):
        from api.routes.admin import ResetSourceRequest
        with pytest.raises(ValidationError):
            ResetSourceRequest(source="x" * 101, confirm="test")
```

### 8.2 Test File: `backend/tests/test_like_escape.py`

```python
"""LIKE pattern escape tests."""
from api.security import escape_like


class TestEscapeLike:
    def test_percent_escaped(self):
        assert escape_like("100%") == "100\\%"

    def test_underscore_escaped(self):
        assert escape_like("a_b") == "a\\_b"

    def test_backslash_escaped(self):
        assert escape_like("a\\b") == "a\\\\b"

    def test_combined(self):
        assert escape_like("%_\\") == "\\%\\_\\\\"

    def test_normal_string_unchanged(self):
        assert escape_like("삼겹살") == "삼겹살"

    def test_empty_string(self):
        assert escape_like("") == ""

    def test_all_percents(self):
        assert escape_like("%%%") == "\\%\\%\\%"
```

### 8.3 Test File: `backend/tests/test_error_handling.py`

```python
"""Error handling tests — verify no information leakage."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.app import create_app
    app = create_app()
    return TestClient(app)


class TestGlobalErrorHandler:
    def test_validation_error_format(self, client):
        """Validation errors should return structured error with code."""
        resp = client.post("/api/products", json={"name": ""})
        assert resp.status_code == 422
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "request_id" in body["error"]

    def test_admin_confirm_no_leak(self, client):
        """Admin endpoints must NOT reveal the expected confirm string."""
        resp = client.post(
            "/api/admin/reset-all",
            json={"confirm": "wrong_string"},
        )
        body = resp.json()
        detail = body.get("detail", body)
        # Must not contain the actual confirm string
        detail_str = str(detail)
        assert "RESET_ALL_DATA" not in detail_str
        assert "DELETE_ALL_PRODUCTS" not in detail_str

    def test_admin_reset_source_no_leak(self, client):
        """reset-source must not reveal DELETE_<SOURCE> pattern."""
        resp = client.post(
            "/api/admin/reset-source",
            json={"source": "emart", "confirm": "wrong"},
        )
        body = resp.json()
        detail_str = str(body)
        assert "DELETE_EMART" not in detail_str


class TestPayloadSizeLimit:
    def test_oversized_payload_rejected(self, client):
        """Payloads exceeding the size limit should return 413."""
        large_payload = {"items": [{"name": "x" * 1000}] * 15_000}
        resp = client.post("/api/ingestions", json=large_payload)
        # Should be either 413 (size middleware) or 422 (Pydantic max_length)
        assert resp.status_code in (413, 422)
```

### 8.4 Test File: `backend/tests/test_getattr_safety.py`

```python
"""Dynamic attribute access safety tests."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.app import create_app
    app = create_app()
    return TestClient(app)


class TestKeywordSortSafety:
    def test_valid_sort_field(self, client):
        resp = client.get("/api/keywords/?sort_by=word")
        assert resp.status_code == 200

    def test_invalid_sort_field_defaults(self, client):
        """Invalid sort_by should fallback, not crash."""
        resp = client.get("/api/keywords/?sort_by=__class__")
        assert resp.status_code == 200

    def test_sort_by_hashed_password_blocked(self, client):
        """Attempting to sort by sensitive field names must be blocked."""
        resp = client.get("/api/keywords/?sort_by=hashed_password")
        assert resp.status_code == 200  # should silently fall back to default


class TestDuplicateFieldSafety:
    def test_invalid_table_rejected(self, client):
        resp = client.post(
            "/api/analytics/duplicates",
            json={"table_name": "users", "fields": ["password"]},
        )
        assert resp.status_code in (400, 422)

    def test_invalid_field_rejected(self, client):
        resp = client.post(
            "/api/analytics/duplicates",
            json={"table_name": "products", "fields": ["hashed_password"]},
        )
        # Should return empty or error, not expose the column
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            assert resp.json() == []

    def test_valid_table_and_fields(self, client):
        resp = client.post(
            "/api/analytics/duplicates",
            json={"table_name": "products", "fields": ["name"]},
        )
        assert resp.status_code == 200
```

### 8.5 Test File: `backend/tests/test_audit_log.py`

```python
"""Audit logging tests."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from storage.models import AuditLog


@pytest.fixture
def client():
    from api.app import create_app
    app = create_app()
    return TestClient(app)


class TestAuditLogging:
    def test_product_create_logged(self, client, db_session):
        """Creating a product should produce an audit log entry."""
        client.post("/api/products", json={"name": "테스트 상품", "unit": "개"})
        logs = db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "CREATE",
                AuditLog.entity_type == "product",
            )
        ).scalars().all()
        assert len(logs) >= 1
        assert logs[-1].entity_type == "product"

    def test_bulk_delete_logged(self, client, db_session):
        """Bulk delete should log with metadata containing IDs."""
        client.post("/api/products/bulk-delete", json={"ids": [1, 2, 3]})
        logs = db_session.execute(
            select(AuditLog).where(AuditLog.action == "BULK_DELETE")
        ).scalars().all()
        assert len(logs) >= 1

    def test_admin_reset_logged(self, client, db_session):
        """Admin reset operations must produce audit entries."""
        client.post(
            "/api/admin/reset-all",
            json={"confirm": "RESET_ALL_DATA"},
        )
        logs = db_session.execute(
            select(AuditLog).where(AuditLog.action == "RESET")
        ).scalars().all()
        assert len(logs) >= 1
        assert logs[-1].entity_type == "all"
```

---

## Implementation Checklist

| # | Task | File(s) | Audit Issue | Priority |
|---|------|---------|-------------|----------|
| 1 | Create `api/security.py` utility module | New file | Foundation | **P0** |
| 2 | Harden all Pydantic models (§2.1–2.7) | 7 route files | Code #14, Arch #8, #13 | **P0** |
| 3 | Add `escape_like()` to all 9 LIKE locations (§3) | 4 files | Code #4 | **P0** |
| 4 | Replace `getattr()` with allowlists (§4) | `keywords.py`, `data_quality.py`, `analytics.py` | Code #5, #12 | **P0** |
| 5 | Add global exception handlers (§5.1) | `app.py` | Code #11 | **P0** |
| 6 | Remove confirm string leaks (§5.2) | `admin.py` | Code #11 | **P0** |
| 7 | Replace `str(e)` patterns (§5.3) | `keywords.py` | Code #11 | **P1** |
| 8 | Wrap admin `except Exception` (§5.4) | `admin.py` | Code #11 | **P1** |
| 9 | Add request size middleware (§6.1) | `app.py` | Code #6, Arch #8 | **P0** |
| 10 | Add uvicorn size limit (§6.2) | `main.py` | Code #6 | **P1** |
| 11 | Create `AuditLog` model (§7.1) | `models.py` | Arch #9 | **P1** |
| 12 | Create `services/audit.py` (§7.2) | New file | Arch #9 | **P1** |
| 13 | Integrate audit calls in all write endpoints (§7.3) | 6 route files | Arch #9 | **P1** |
| 14 | Run Alembic migration for `audit_log` (§7.4) | Alembic | Arch #9 | **P1** |
| 15 | Write & run all test suites (§8) | `tests/` | All | **P0** |

**Estimated effort**: 3–4 days for all items.

---

## Standard Error Response Format

All error responses from the API (after these changes) will follow this schema:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "입력 데이터가 올바르지 않습니다.",
    "request_id": "a1b2c3d4e5f6"
  }
}
```

For validation errors (422), an additional `details` array is provided:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "입력 데이터가 올바르지 않습니다.",
    "request_id": "a1b2c3d4e5f6",
    "details": [
      {"field": "body.name", "message": "String should have at most 255 characters"},
      {"field": "body.ids", "message": "List should have at most 500 items"}
    ]
  }
}
```

Error codes:

| Code | HTTP Status | Meaning |
|------|------------|---------|
| `VALIDATION_ERROR` | 422 | Pydantic validation failure |
| `NOT_FOUND` | 404 | Resource not found |
| `CONFLICT` | 409 | Duplicate resource |
| `CONFIRM_MISMATCH` | 400 | Wrong confirmation string (no hint given) |
| `PAYLOAD_TOO_LARGE` | 413 | Request body exceeds 10 MB |
| `INTERNAL_ERROR` | 500 | Unhandled server error (details logged, not exposed) |
| `INVALID_SORT_FIELD` | 400 | Sort field not in allowlist |
| `INVALID_TABLE` | 400 | Table name not in allowlist |
| `INVALID_FIELD` | 400 | Field name not in allowlist |
| `BULK_LIMIT_EXCEEDED` | 400 | Bulk operation exceeds max items |
