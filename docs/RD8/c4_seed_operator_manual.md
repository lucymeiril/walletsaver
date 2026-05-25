# RD8 C4 시드 운영 매뉴얼

**작성일**: 2026-05-25  
**대상 독자**: DB 운영자, 백엔드 엔지니어  
**관련 리비전**: `h6a7b8c9d0e1`, `h7b8c9d0e1f2`

---

## 개요

RD8 C4는 두 가지 시드 작업으로 구성된다.

| 작업 | 스크립트 | 대상 테이블 | 건수 |
|------|---------|------------|------|
| 카테고리 시드 | `tools/rd8_seed_categories.py` | `categories` | 265건 |
| 매칭 시드 | `tools/rd8_seed_matching.py` | `matching_entries` | 27건 |

두 스크립트 모두 **기본적으로 dry-run** 모드로 동작한다. 실제 DB 반영은 `--commit` 플래그가 필요하다.

---

## 사전 요구 사항

### 환경 변수

```powershell
$env:DATABASE_URL = "sqlite:///packages/db-admin/backend/walletguardian.db"
```

프로덕션 PostgreSQL인 경우:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://user:password@host:5432/walletguardian"
```

### Alembic 마이그레이션 확인

C4 시드 실행 전 반드시 두 마이그레이션이 적용돼 있어야 한다.

```powershell
cd packages\db-admin\backend
py -3 -m alembic current   # h7b8c9d0e1f2 (head) 이어야 함
```

head가 아닌 경우:

```powershell
py -3 -m alembic upgrade head
```

---

## 워크플로우 1: 카테고리 시드

### 1-1. Dry-run (검토)

```powershell
cd E:\pdf\capston01
py -3 tools/rd8_seed_categories.py
```

출력 예시:

```
[INFO] YAML 노드: 265개
[INFO] 모드: dry-run (실제 반영 없음)
╔══════════════════════════════╗
║      카테고리 시드 결과 (dry-run)  ║
╠══════════════════════════════╣
║  created   :            265  ║
║  updated   :              0  ║
║  unchanged :              0  ║
║  합계      :            265  ║
╚══════════════════════════════╝
```

### 1-2. 실제 반영

```powershell
py -3 tools/rd8_seed_categories.py --commit
```

### 1-3. 검증 항목

반영 후 자동으로 무결성 검증이 실행된다:

- `source='rd8_seed'` 카운트 = 265
- leaf 카운트 = 219
- 고아 노드(orphan) = 0
- 자기참조(self-ref) = 0

수동 확인:

```sql
-- SQLite
SELECT COUNT(*) FROM categories WHERE source = 'rd8_seed';           -- 265
SELECT COUNT(*) FROM categories WHERE source = 'rd8_seed'
  AND id NOT IN (SELECT DISTINCT parent_id FROM categories WHERE parent_id IS NOT NULL); -- 219 (leaf)
```

### 1-4. 멱등성

같은 YAML로 재실행하면 `unchanged=265`가 돼야 한다:

```powershell
py -3 tools/rd8_seed_categories.py --commit
# → unchanged : 265
```

---

## 워크플로우 2: 매칭 시드

### 2-1. Dry-run (검토)

```powershell
py -3 tools/rd8_seed_matching.py
```

### 2-2. 실제 반영

```powershell
py -3 tools/rd8_seed_matching.py --commit
```

출력 예시:

```
╔══════════════════════════════╗
║           매칭 시드 결과           ║
╠══════════════════════════════╣
║  created   :             27  ║
║  updated   :              0  ║
║  unchanged :              0  ║
║  합계      :             27  ║
╚══════════════════════════════╝
[검증] matching_entries[source=rd8_c3_seed] = 27건
```

### 2-3. 검증

```sql
SELECT COUNT(*) FROM matching_entries WHERE source = 'rd8_c3_seed';  -- 27
```

---

## 워크플로우 3: 신규 카테고리 등록 (운영 중)

운영 중 외부 LLM이 새 카테고리를 제안하는 경우의 흐름:

```
외부 LLM 제안
    │
    ▼
category_review_queue 테이블 (status='pending')
    │
    ▼  운영자 검토 (Admin UI 또는 SQL)
    │
    ├─ 거부 → status='rejected'
    │
    └─ 승인 → 승인 API 호출
               → categories 테이블에 INSERT
               → status='approved'
```

**절대 직접 `categories` 테이블에 INSERT하지 말 것.** 반드시 `category_review_queue`를 통해야 한다.

---

## 워크플로우 4: 신규 매칭 등록 (운영 중)

```
외부 LLM L3 분류 결과
    │
    ▼
L3 임포트 미리보기 (dry-run)
    │
    ▼  운영자 검토 (confidence, category_id 확인)
    │
    ├─ 거부 → 폐기
    │
    └─ 승인 → matching_entries UPSERT (match_key 기준)
```

**match_key 형식**: `brand|name_core|pack_qty|pack_unit`

- `pack_qty`: 소수점 6자리 (`%.6f`)
- 단위 정규화: L→ml (×1000), KG→g (×1000)
- 예: `"CJ|햇반|210.000000|g"`

---

## 주의 사항

### ⚠️ SQLite CHECK 제약 조건

SQLite는 `ALTER TABLE ... MODIFY COLUMN`이 없다. `source` 컬럼에 새 허용값을 추가하려면:

1. `models.py`의 `_MATCHING_ENTRY_VALID_SOURCES` frozenset에 추가
2. `MatchingEntry.__table_args__` 의 `ck_matching_source_enum` CHECK 문자열에 추가
3. `op.batch_alter_table(recreate="auto")` 방식으로 Alembic 마이그레이션 작성

### ⚠️ YAML 수정 시

`packages/shared/data/categories_rd8.yaml`을 수정한 경우, 반드시:

1. 변경 전 `--dry-run`으로 `updated` 건수 확인
2. 검토 후 `--commit`

### ⚠️ gift 루트 노드

`docs/RD8/categories_final_opus.md`는 루트 14개라고 명시하지만, 실제 YAML에는 `gift`를 포함해 15개가 있다. 이 불일치는 문서 오류이며, 시드 결과(265건)가 정확하다.

---

## 파일 목록

| 파일 | 역할 |
|------|------|
| `tools/rd8_seed_categories.py` | 카테고리 YAML→DB UPSERT |
| `tools/rd8_seed_matching.py` | 매칭 27건 시드 |
| `packages/shared/data/categories_rd8.yaml` | 265 카테고리 YAML 소스 |
| `packages/db-admin/backend/storage/migrations/versions/h6a7b8c9d0e1_rd8_categories_seed_columns.py` | categories 7컬럼 + matching_entries source CHECK 확장 |
| `packages/db-admin/backend/storage/migrations/versions/h7b8c9d0e1f2_rd8_matching_aliases.py` | matching_entries.aliases 스키마 드리프트 수정 |
| `packages/db-admin/backend/tests/test_categories_seed.py` | C4 시드 자동화 테스트 (9건) |
