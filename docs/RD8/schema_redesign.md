# RD8 스키마 재설계안 (WalletSavior 핫딜 비교 사이트)

> 작성 기준: `packages/db-admin/backend/storage/models.py`, `services/bundle_import.py`, `docs/RD8/real_data_gap_catalog.md` 실 파일 기반. 추측 없음.

---

## A. 현 스키마 결함 진단

### A-1. Product 현행 정의 (models.py:147~189)

```python
class Product(Base):
    __tablename__ = "products"
    id: Mapped[int]
    name: Mapped[str]          # "농심 신라면" — brand+name_core 합성 평탄화
    category_id: Mapped[Optional[str]]
    unit: Mapped[str]          # "개" 기본값 — pack_qty 없음
    description: Mapped[Optional[str]]
    image_url: Mapped[Optional[str]]
    attributes: Mapped[Optional[dict]]
    is_active: Mapped[bool]
    source_type: Mapped[Optional[str]]   # "mart_crawl" 고정 — 마트 식별 불가
    categorization_confidence: Mapped[Optional[float]]
    categorization_method: Mapped[Optional[str]]
```

**누락 컬럼 표**

| 필요 컬럼 | 현황 | 영향 |
|---|---|---|
| `brand` | ❌ 없음 (name에 합성) | 브랜드 필터링 불가 |
| `name_core` | ❌ 없음 | 중복 탐지 키 부재 |
| `pack_qty` | ❌ 없음 (unit에 일부 혼입) | 용량 비교 불가 |
| `pack_unit` | ❌ 없음 (unit으로 대체 시도) | 환산 단위 불명 |
| `display_name` | ❌ 없음 | UI 합성명 DB 캐싱 없음 |
| `unit_kind` | ❌ 없음 | weight/volume/count/pack 분류 불가 |
| `source_marts` | ❌ 없음 | 수집 마트 집합 조회 불가 |
| UNIQUE(brand,name_core,pack_qty,pack_unit) | ❌ 없음 | 40배 중복 INSERT 허용 |

### A-2. BaselinePrice 현행 정의 (models.py:196~219)

```python
class BaselinePrice(Base):
    __tablename__ = "baseline_prices"
    id: Mapped[int]
    product_id: Mapped[int]
    price: Mapped[float]
    source: Mapped[str]        # 마트명 자유 문자열 — mart_code 없음, 인덱스만
    unit: Mapped[str]
    recorded_at: Mapped[datetime]
    region: Mapped[Optional[str]]
    raw_data: Mapped[Optional[dict]]
```

**누락 컬럼 표**

| 필요 컬럼 | 현황 | 영향 |
|---|---|---|
| `mart_code` (NOT NULL, indexed) | ❌ `source` 자유문자열만 | 마트별 집계 쿼리 불신뢰 |
| `pack_qty_snapshot` | ❌ 없음 | 패키지 변동 추적 불가 |
| `pack_unit_snapshot` | ❌ 없음 | 단위 변경 이력 유실 |
| `unit_price_normalized` | ❌ 없음 | 100g당/100ml당 비교 불가 |
| `unit_price_basis` | ❌ 없음 | 정규화 기준 단위 불명 |
| UNIQUE(product_id, mart_code, recorded_at) | ❌ 없음 | 동일 마트+날짜 중복 행 허용 |

### A-3. MatchingEntry 현행 정의 (models.py:1132~1252)

현행은 대체로 양호. match_key UNIQUE + brand/name_core/pack_qty/pack_unit 분해 컬럼 존재.

**추가 권장 컬럼 표**

| 필요 컬럼 | 현황 | 영향 |
|---|---|---|
| `pack_unit_kind` (weight/volume/count/pack) | ❌ 없음 | 환산 가능 여부 판단 불가 |
| `source_record_key` 직접 컬럼 | ❌ notes에 자유형 | 멱등성 키 부재 |

### A-4. bundle_import.py INSERT 경로 — "왜 매번 새 product가 생기는가"

`services/bundle_import.py:404~436` 핵심 경로:

```python
# bundle_import.py:405~421
product = None
if matching_entry.canonical_product_id:
    product = session.query(Product).filter_by(
        id=matching_entry.canonical_product_id
    ).first()

if product is None:                     # ← 문제: canonical_product_id가 NULL이면
    name = f"{matching_entry.brand or ''} {matching_entry.name_core or ''}".strip()
    product = Product(                  #   매번 새 Product를 INSERT
        name=name,
        unit=str(matching_entry.pack_unit or "개"),
        source_type="mart_crawl",
    )
    session.add(product)
    session.flush()
    # ★ canonical_product_id를 matching_entry에 write-back 하지 않음!
    # → 다음 bundle import 때도 canonical_product_id == NULL → 또 새 INSERT
```

**근본 원인**: `matching_entry.canonical_product_id`는 NULL(fixture에서 미지정)이고, product 생성 후 write-back 없음. 결과: 같은 match_key가 10번 import되면 Product 10건 생성.

또한 BaselinePrice INSERT는 UPSERT 없이 단순 `session.add(bp)` (bundle_import.py:423~435), 같은 mart+recorded_at 키로 중복 행 무제한 생성.

---

## B. 신 스키마 설계안

### B-1. Product 정규화 컬럼 추가

```python
class Product(Base):
    __tablename__ = "products"

    # ── 기존 컬럼 유지 ──────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # 레거시, 하위호환
    category_id: Mapped[Optional[str]] = mapped_column(ForeignKey("categories.id"))
    unit: Mapped[str] = mapped_column(String(50), default="개")     # 레거시
    description: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(String(500))
    attributes: Mapped[Optional[dict]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(20), default="mart_crawl")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── 신규 정규화 컬럼 ─────────────────────────────────
    brand: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True,
        comment="브랜드명. NB=브랜드명, PB=None(import 시 mart_code로 fallback)"
    )
    name_core: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="상품 핵심명 (브랜드·용량 제외). 예: '신라면', '햇반'"
    )
    pack_qty: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="용량/수량 숫자. 예: 120.0, 210.0"
    )
    pack_unit: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="용량 단위. 예: g, ml, 개, 봉, 개입, 세트 등"
    )
    unit_kind: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="단위 분류: weight | volume | count | pack"
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(400), nullable=True,
        comment="UI 표시명 (DB 캐시). brand가 name_core에 포함되면 중복 제거 후 저장"
    )
    source_marts: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True,
        comment="수집된 마트 코드 캐시. 예: ['emart','homeplus']. baseline_prices에서 파생."
    )

    __table_args__ = (
        # ★ 핵심 UNIQUE: 중복 product 방지
        UniqueConstraint(
            "brand", "name_core", "pack_qty", "pack_unit",
            name="uq_product_canonical",
        ),
        Index("ix_products_name", "name"),
        Index("ix_products_category", "category_id"),
        Index("ix_products_source_type", "source_type"),
        Index("ix_products_active", "is_active"),
        Index("ix_products_brand", "brand"),
        Index("ix_products_name_core", "name_core"),
        Index("ix_products_unit_kind", "unit_kind"),
    )
```

> **NB/PB 정책**: brand=NULL인 경우 import 로직에서 mart_code를 PB fallback으로 채운다. 컬럼 레벨에서는 NULL 허용 (DB가 fallback 강제 안 함).

> **SQLite NULL UNIQUE 주의**: SQLite는 UNIQUE constraint에서 NULL을 서로 다른 값으로 취급한다. brand=NULL, name_core='골드키위', pack_qty=1.0, pack_unit='EA' 조합이 여러 행 허용될 수 있음. import 로직에서 NULL 컬럼을 포함한 `find_or_create` 쿼리 시 `IS NULL` 조건을 명시적으로 써야 한다.

---

### B-2. 마트 식별 전략

**결론: products에는 mart 컬럼을 두지 않는다 (canonical 단일 행 원칙).**

마트별 데이터는 `baseline_prices.mart_code` + `product_matches.mart_name`에서 보유.

**`source_marts` JSON 캐시 컬럼 권장 여부:**

| 방안 | 장점 | 단점 |
|---|---|---|
| `source_marts` JSON 캐시 (Product에 저장) | 마트 집합 빠른 조회, JOIN 불필요 | baseline_prices INSERT/DELETE 시 동기화 필요, 정합성 위험 |
| Derived View (`v_product_source_marts`) | 항상 정확, 유지보수 부담 없음 | 매번 GROUP BY 집계 비용 |
| 캐시 없이 baseline_prices JOIN | 단순 | 목록 페이지에서 N번 JOIN 비용 |

**권장**: 초기에는 `source_marts` JSON 캐시 컬럼 사용. bundle_import의 apply_products 완료 직후 업데이트. 이후 규모 증가 시 Derived View로 교체.

---

### B-3. 단위 분류 (`unit_kind`)

**enum 값 및 한국 마트 실 단위 목록**

```python
# 신규 enum (String 컬럼으로 저장, 코드에서 열거형 검사)
UNIT_KIND_WEIGHT  = "weight"   # 환산 가능 (g ↔ kg)
UNIT_KIND_VOLUME  = "volume"   # 환산 가능 (ml ↔ L)
UNIT_KIND_COUNT   = "count"    # 개수 단위 (환산 불가, 개/EA/알/마리/팩·낱개 등)
UNIT_KIND_PACK    = "pack"     # 복합 묶음 (환산 불가 — 봉/개입/세트/팩/캔/병/포/매/구/입/장/구성/단/망/롤/컵/통/박스)
```

**단위 → unit_kind 매핑 테이블**

| unit_kind | 해당 단위 (한국 마트 실 단위) |
|---|---|
| `weight` | g, kg, mg, 근(300g), ton |
| `volume` | ml, L, cc, dl |
| `count` | 개, EA, 알, 마리, 미, 모, 두, 포기, 단(채소 다발 = count) |
| `pack` | 봉, 개입, 세트, 팩, 캔, 병, 포(포장), 매, 구, 입, 장, 구성, 단(묶음), 망, 롤, 컵, 통, 박스, 줄, 판, 쌍, 켤레, 다스, T(티백), P(팩 약어) |

> `단`은 채소 다발(count)과 묶음 상품(pack) 양쪽에 쓰인다. raw_payload의 pack_qty가 1이면 count, >1이면 pack으로 분류. import 로직에서 결정.

**환산 가능 여부**:
- `weight`: g 기준으로 환산 가능 (`unit_price_normalized` = 원/100g)
- `volume`: ml 기준으로 환산 가능 (`unit_price_normalized` = 원/100ml)
- `count` / `pack`: 환산 불가. `unit_price_normalized = NULL` 허용.

---

### B-4. title 합성/표시 규칙

**합성 로직**:
```python
def build_display_name(brand: str | None, name_core: str | None,
                       pack_qty: float | None, pack_unit: str | None) -> str:
    # brand가 name_core 첫 부분에 포함되면 제거 (예: "코카콜라 코카콜라 콜라" → "코카콜라 콜라")
    if brand and name_core and name_core.startswith(brand):
        name_part = name_core
    elif brand and name_core:
        name_part = f"{brand} {name_core}"
    else:
        name_part = name_core or brand or ""

    # 용량 표시
    if pack_qty and pack_unit:
        qty_str = f"{int(pack_qty)}" if pack_qty == int(pack_qty) else f"{pack_qty}"
        return f"{name_part} {qty_str}{pack_unit}".strip()
    return name_part.strip()
```

**저장 vs. 매번 합성 비교**:

| 방안 | 장점 | 단점 |
|---|---|---|
| `display_name` 컬럼 저장 (권장) | 정렬·검색 인덱스 가능, API 응답 빠름 | brand/name_core 변경 시 update 필요 |
| UI에서 매번 합성 | 로직 단순, DB 컬럼 불필요 | 클라이언트 언어마다 합성 로직 중복 |

**권장**: `display_name` 컬럼 DB 저장. bundle_import의 product 생성/갱신 시점에 한 번 계산.

---

### B-5. BaselinePrice 보강

```python
class BaselinePrice(Base):
    __tablename__ = "baseline_prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[float] = mapped_column(Float, nullable=False)

    # ── 신규: 마트 식별 ─────────────────────────────────
    mart_code: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="정규화된 마트 코드. 예: emart, homeplus, lottemart, costco"
    )

    # ── 기존 source 유지 (하위호환, mart_code와 동일값 채움) ──
    source: Mapped[str] = mapped_column(String(50), nullable=False)

    # ── 단위 (기존 unit 유지 + 스냅샷 신규 추가) ────────────
    unit: Mapped[str] = mapped_column(String(50), nullable=False)  # 레거시

    pack_qty_snapshot: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="가격 수집 시점의 pack_qty. 패키지 변동 추적용."
    )
    pack_unit_snapshot: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="가격 수집 시점의 pack_unit. 패키지 변동 추적용."
    )

    # ── 신규: 정규화 단가 ──────────────────────────────────
    unit_price_normalized: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="환산 단가. weight→원/100g, volume→원/100ml. count/pack은 NULL."
    )
    unit_price_basis: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True,
        comment="정규화 기준 단위. 예: g, ml, 개"
    )

    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    region: Mapped[Optional[str]] = mapped_column(String(50))
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)

    product: Mapped["Product"] = relationship(back_populates="baseline_prices")

    __table_args__ = (
        # ★ 핵심 UNIQUE: 같은 마트+날짜 중복 방지
        UniqueConstraint(
            "product_id", "mart_code", "recorded_at",
            name="uq_baseline_product_mart_date",
        ),
        Index("ix_baseline_product_date", "product_id", "recorded_at"),
        Index("ix_baseline_product_source", "product_id", "source"),
        Index("ix_baseline_mart_code", "mart_code"),
        Index("ix_baseline_product_mart", "product_id", "mart_code"),
    )
```

---

### B-6. MatchingEntry 추가 권장

현행 MatchingEntry는 match_key UNIQUE + 분해 필드 존재로 기본 구조는 양호.

**추가 권장 컬럼** (models.py:1166 이후):

```python
# MatchingEntry에 추가

pack_unit_kind: Mapped[Optional[str]] = mapped_column(
    String(20), nullable=True,
    comment="단위 분류 캐시: weight | volume | count | pack. import 시 pack_unit에서 파생."
)

source_record_key: Mapped[Optional[str]] = mapped_column(
    String(255), nullable=True,
    comment="크롤러 원본 레코드 키 (raw_payload.attributes.source_record_key). 멱등성 보장용."
)
```

**__table_args__ 추가**:
```python
Index("ix_matching_unit_kind", "pack_unit_kind"),
Index("ix_matching_source_record_key", "source_record_key"),
```

---

## C. 마이그레이션 전략

### C-1. 기존 800건 dirty 데이터 처리

**권장: 전부 삭제 후 재구축.**

이유:
- 800건 = 20 상품 × 40 중복. 정규화 컬럼 모두 NULL.
- baseline_prices: mart_code 없음, 모든 product당 1건(avg=1.0), 마트 비교 불가.
- attributes/image_url/description 0/800 채움 — 재구축해도 손실 없음.

```sql
-- 마이그레이션 스크립트에서 실행 (데이터 전부 삭제)
DELETE FROM baseline_prices;
DELETE FROM products;
-- matching_entries는 유지 (match_key 룩업 테이블이므로 재사용 가능)
```

### C-2. Alembic revision 변경 순서

**마이그레이션 경로**: `packages/db-admin/backend/storage/migrations/versions/`

```
revision 1: add_product_canonical_columns
    → products에 brand, name_core, pack_qty, pack_unit, unit_kind, display_name, source_marts 추가
    → UNIQUE constraint uq_product_canonical 추가

revision 2: add_baseline_mart_code
    → baseline_prices에 mart_code, pack_qty_snapshot, pack_unit_snapshot,
      unit_price_normalized, unit_price_basis 추가
    → UNIQUE constraint uq_baseline_product_mart_date 추가
    → source 컬럼 유지 (하위호환)

revision 3: add_matching_entry_extensions
    → matching_entries에 pack_unit_kind, source_record_key 추가
```

### C-3. 핵심 op 스케치

```python
# revision 1: add_product_canonical_columns
def upgrade():
    # 기존 dirty 데이터 삭제
    op.execute("DELETE FROM baseline_prices")
    op.execute("DELETE FROM products")

    op.add_column("products", sa.Column("brand", sa.String(200), nullable=True))
    op.add_column("products", sa.Column("name_core", sa.String(500), nullable=True))
    op.add_column("products", sa.Column("pack_qty", sa.Float(), nullable=True))
    op.add_column("products", sa.Column("pack_unit", sa.String(50), nullable=True))
    op.add_column("products", sa.Column("unit_kind", sa.String(20), nullable=True))
    op.add_column("products", sa.Column("display_name", sa.String(400), nullable=True))
    op.add_column("products", sa.Column("source_marts", sa.JSON(), nullable=True))

    op.create_unique_constraint(
        "uq_product_canonical",
        "products",
        ["brand", "name_core", "pack_qty", "pack_unit"],
    )
    op.create_index("ix_products_brand", "products", ["brand"])
    op.create_index("ix_products_name_core", "products", ["name_core"])
    op.create_index("ix_products_unit_kind", "products", ["unit_kind"])

def downgrade():
    op.drop_constraint("uq_product_canonical", "products", type_="unique")
    op.drop_index("ix_products_unit_kind", "products")
    op.drop_index("ix_products_name_core", "products")
    op.drop_index("ix_products_brand", "products")
    for col in ["source_marts", "display_name", "unit_kind", "pack_unit", "pack_qty", "name_core", "brand"]:
        op.drop_column("products", col)


# revision 2: add_baseline_mart_code
def upgrade():
    op.add_column("baseline_prices", sa.Column("mart_code", sa.String(50), nullable=True))
    op.add_column("baseline_prices", sa.Column("pack_qty_snapshot", sa.Float(), nullable=True))
    op.add_column("baseline_prices", sa.Column("pack_unit_snapshot", sa.String(50), nullable=True))
    op.add_column("baseline_prices", sa.Column("unit_price_normalized", sa.Float(), nullable=True))
    op.add_column("baseline_prices", sa.Column("unit_price_basis", sa.String(10), nullable=True))

    # 기존 source 값으로 mart_code 초기화
    op.execute("UPDATE baseline_prices SET mart_code = source WHERE mart_code IS NULL")

    # NOT NULL로 변경 (SQLite는 recreate 방식 필요 — 실제 마이그레이션 시 batch_alter_table 사용)
    # op.alter_column("baseline_prices", "mart_code", nullable=False)

    op.create_unique_constraint(
        "uq_baseline_product_mart_date",
        "baseline_prices",
        ["product_id", "mart_code", "recorded_at"],
    )
    op.create_index("ix_baseline_mart_code", "baseline_prices", ["mart_code"])
    op.create_index("ix_baseline_product_mart", "baseline_prices", ["product_id", "mart_code"])


# revision 3: add_matching_entry_extensions
def upgrade():
    op.add_column("matching_entries", sa.Column("pack_unit_kind", sa.String(20), nullable=True))
    op.add_column("matching_entries", sa.Column("source_record_key", sa.String(255), nullable=True))
    op.create_index("ix_matching_unit_kind", "matching_entries", ["pack_unit_kind"])
    op.create_index("ix_matching_source_record_key", "matching_entries", ["source_record_key"])
```

> **SQLite 주의**: ALTER TABLE로 NOT NULL 컬럼 추가 불가. `batch_alter_table` 사용 또는 nullable=True로 추가 후 데이터 채운 뒤 별도 revision에서 NOT NULL 적용.

---

## D. bundle_import 로직 재설계

### D-1. 현 INSERT 경로 문제 인용

```python
# bundle_import.py:404~435 (현행)
product = None
if matching_entry.canonical_product_id:   # ← NULL이면 건너뜀
    product = session.query(Product).filter_by(id=matching_entry.canonical_product_id).first()

if product is None:
    product = Product(name=name, ...)     # ← 매번 새 INSERT
    session.add(product)
    session.flush()
    # ← canonical_product_id write-back 없음!

bp = BaselinePrice(...)                   # ← UPSERT 아닌 단순 INSERT
session.add(bp)
```

### D-2. 재설계: find_or_create 패턴

```python
# 재설계 의사코드 — apply_products 내부

def _find_or_create_product(session: Session, me: MatchingEntry) -> Product:
    """brand/name_core/pack_qty/pack_unit 조합으로 product 찾거나 생성."""
    # SQLite NULL UNIQUE 주의: IS NULL 조건 명시 필수
    q = session.query(Product)
    if me.brand is not None:
        q = q.filter(Product.brand == me.brand)
    else:
        q = q.filter(Product.brand.is_(None))
    if me.name_core is not None:
        q = q.filter(Product.name_core == me.name_core)
    else:
        q = q.filter(Product.name_core.is_(None))
    q = q.filter(Product.pack_qty == me.pack_qty)
    if me.pack_unit is not None:
        q = q.filter(Product.pack_unit == me.pack_unit)
    else:
        q = q.filter(Product.pack_unit.is_(None))

    product = q.first()
    if product is None:
        unit_kind = _classify_unit_kind(me.pack_unit)
        display_name = _build_display_name(me.brand, me.name_core, me.pack_qty, me.pack_unit)
        product = Product(
            name=display_name,           # 레거시 호환
            brand=me.brand,
            name_core=me.name_core,
            pack_qty=me.pack_qty,
            pack_unit=me.pack_unit,
            unit_kind=unit_kind,
            display_name=display_name,
            category_id=me.category_id,
            source_type="mart_crawl",
        )
        session.add(product)
        session.flush()

    # ★ canonical_product_id write-back — 다음 번 import에서 재활용
    if not me.canonical_product_id:
        me.canonical_product_id = str(product.id)
        session.flush()

    return product


def _classify_unit_kind(pack_unit: str | None) -> str:
    """pack_unit 문자열 → unit_kind 분류."""
    if not pack_unit:
        return "count"
    WEIGHT = {"g", "kg", "mg", "근", "ton"}
    VOLUME = {"ml", "l", "L", "cc", "dl"}
    COUNT  = {"개", "EA", "알", "마리", "미", "모", "두", "포기"}
    PACK   = {"봉", "개입", "세트", "팩", "캔", "병", "포", "매", "구", "입",
              "장", "구성", "단", "망", "롤", "컵", "통", "박스", "줄", "판",
              "쌍", "켤레", "다스", "T", "P"}
    u = pack_unit.strip()
    if u in WEIGHT: return "weight"
    if u in VOLUME: return "volume"
    if u in COUNT:  return "count"
    if u in PACK:   return "pack"
    return "count"  # 미분류 기본값


def _upsert_baseline_price(session: Session, product: Product,
                            row: dict, me: MatchingEntry,
                            mart_code: str, captured_dt: datetime) -> None:
    """product+mart_code+recorded_at 키로 UPSERT."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    pack_unit = me.pack_unit
    unit_kind = _classify_unit_kind(pack_unit)
    price_val = float(row["price"])

    # 정규화 단가 계산
    unit_price_normalized = None
    unit_price_basis = None
    if unit_kind == "weight" and me.pack_qty and me.pack_qty > 0:
        qty_in_g = me.pack_qty * (1000 if (me.pack_unit or "").lower() == "kg" else 1)
        unit_price_normalized = round(price_val / qty_in_g * 100, 4)
        unit_price_basis = "g"
    elif unit_kind == "volume" and me.pack_qty and me.pack_qty > 0:
        qty_in_ml = me.pack_qty * (1000 if (me.pack_unit or "").lower() == "l" else 1)
        unit_price_normalized = round(price_val / qty_in_ml * 100, 4)
        unit_price_basis = "ml"

    stmt = sqlite_insert(BaselinePrice).values(
        product_id=product.id,
        mart_code=mart_code,
        source=mart_code,
        price=price_val,
        unit=str(pack_unit or "개"),
        pack_qty_snapshot=me.pack_qty,
        pack_unit_snapshot=pack_unit,
        unit_price_normalized=unit_price_normalized,
        unit_price_basis=unit_price_basis,
        recorded_at=captured_dt,
        raw_data={
            "raw_id": row.get("raw_id"),
            "match_key": row.get("match_key"),
            "mart": mart_code,
        },
    ).on_conflict_do_update(
        index_elements=["product_id", "mart_code", "recorded_at"],
        set_={"price": price_val,
              "unit_price_normalized": unit_price_normalized,
              "updated_at": datetime.now(timezone.utc)},
    )
    session.execute(stmt)


def _update_source_marts_cache(session: Session, product: Product, mart_code: str) -> None:
    """source_marts JSON 캐시 갱신 (중복 없이 추가)."""
    current = product.source_marts or []
    if mart_code not in current:
        product.source_marts = sorted(set(current) | {mart_code})
        session.flush()
```

### D-3. 멱등성 보장

- **같은 raw가 두 번 들어올 때**: `source_record_key`(= raw_payload.attributes.source_record_key)를 MatchingEntry에 저장하고, apply_products 진입 시 이미 처리된 source_record_key는 skip.

```python
# 멱등성 체크 (apply_products 내부 루프)
source_record_key = (row.get("raw_payload") or {}).get("attributes", {}).get("source_record_key")
if source_record_key:
    already = session.query(BaselinePrice).join(Product).filter(
        Product.id == product.id,
        BaselinePrice.raw_data["source_record_key"].as_string() == source_record_key,
        BaselinePrice.mart_code == mart_code,
    ).first()
    if already:
        skipped += 1
        continue
```

### D-4. attributes/image_url/description 매핑

raw_payload 구조 (real_data_gap_catalog.md §7):

```json
{
  "name": "...",
  "brand": "...",
  "name_core": "...",
  "pack_qty": 120.0,
  "pack_unit": "g",
  "sale_price": 1500,
  "original_price": 2000,
  "attributes": {
    "source_name": "emart",
    "brand": "농심",
    "source_record_key": "emart-12345"
  }
}
```

**매핑 로직**:

```python
def _extract_product_fields(row: dict) -> dict:
    """raw_payload에서 Product 보강 필드 추출."""
    raw = row.get("raw_payload") or {}
    attrs = raw.get("attributes") or {}
    return {
        "image_url": raw.get("image_url") or raw.get("img_url"),
        "description": raw.get("description") or raw.get("desc"),
        "attributes": {
            "source_name": attrs.get("source_name"),
            "source_record_key": attrs.get("source_record_key"),
            "original_brand": attrs.get("brand"),
        },
    }

# apply_products 내에서 product 생성/갱신 시 적용:
extra = _extract_product_fields(row)
if not product.image_url and extra["image_url"]:
    product.image_url = extra["image_url"]
if not product.description and extra["description"]:
    product.description = extra["description"]
if extra["attributes"]:
    product.attributes = {**(product.attributes or {}), **extra["attributes"]}
```

---

## E. 검증 게이트 (D phase 완료 후 통과 기준)

```sql
-- 게이트 1: distinct product 수 == distinct (brand, name_core, pack_qty, pack_unit) 수
SELECT
    COUNT(*) AS total_products,
    COUNT(DISTINCT COALESCE(brand,'__NULL__') || '|' ||
                   COALESCE(name_core,'__NULL__') || '|' ||
                   COALESCE(CAST(pack_qty AS TEXT),'__NULL__') || '|' ||
                   COALESCE(pack_unit,'__NULL__')) AS distinct_canonical
FROM products
WHERE is_active = 1;
-- 기대: total_products == distinct_canonical

-- 게이트 2: 모든 product가 baseline_prices >= 1 (이상적으로 >= 2 마트)
SELECT
    COUNT(*) AS products_no_price
FROM products p
WHERE is_active = 1
  AND NOT EXISTS (SELECT 1 FROM baseline_prices bp WHERE bp.product_id = p.id);
-- 기대: 0

SELECT
    COUNT(*) AS products_single_mart,
    COUNT(*) FILTER (WHERE mart_cnt >= 2) AS products_multi_mart
FROM (
    SELECT product_id, COUNT(DISTINCT mart_code) AS mart_cnt
    FROM baseline_prices
    GROUP BY product_id
) t;
-- 이상적: products_multi_mart == total products

-- 게이트 3: products.brand 결측률
SELECT
    ROUND(100.0 * SUM(CASE WHEN brand IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS brand_null_pct
FROM products WHERE is_active = 1;
-- 기대: PB 상품은 source_marts[0]을 fallback으로 채웠으므로 0%

-- 게이트 4: display_name 첫 두 단어 중복 = 0
SELECT display_name,
       COUNT(*) AS cnt
FROM products
WHERE is_active = 1
GROUP BY display_name
HAVING cnt > 1;
-- 기대: 0건

-- 게이트 5: unit_price_normalized — weight/volume인 경우 100% 채워짐
SELECT
    COUNT(*) AS weight_vol_with_null_price
FROM baseline_prices bp
JOIN products p ON bp.product_id = p.id
WHERE p.unit_kind IN ('weight', 'volume')
  AND bp.unit_price_normalized IS NULL;
-- 기대: 0
```

---

## F. Open Questions (사용자 결정 필요)

| # | 질문 | 옵션 A | 옵션 B | 비고 |
|---|---|---|---|---|
| F-1 | `source_marts` JSON 캐시 도입 여부 | 도입 (Product에 저장, 동기화 필요) | Derived View로 대체 | 초기엔 캐시 권장, 추후 교체 |
| F-2 | 기존 800건 삭제 시점 | Revision 1 업그레이드 시 자동 삭제 | 별도 수동 스크립트 | 자동이 안전하나 복구 불가 |
| F-3 | SQLite → PostgreSQL 전환 계획 | SQLite 유지 + batch_alter_table | 조기 전환 후 UPSERT 단순화 | UNIQUE NULL 처리 난이도 변동 |
| F-4 | `display_name` 다국어 지원 | 한국어 단일 | 별도 `display_names` 테이블 | 현재는 한국어 단일로 충분 |
| F-5 | `pack_unit_kind` 미분류('unknown') 허용 여부 | count 기본값으로 fallback | 별도 'unknown' enum 추가 | 운영 모니터링 용이성 trade-off |
| F-6 | MatchingEntry `source_record_key` 중복 처리 | UNIQUE constraint 추가 | 인덱스만 (중복 허용) | 멱등성 강도 결정 |
