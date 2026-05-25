"""test_categories_seed.py — RD8 C4 카테고리 시드 검증 테스트.

대상:
  - rd8_seed_categories.py 의 dry-run 카운트 일치 (265건)
  - parent 무결성 (child.parent_id ∈ 적재된 category ID)
  - keyword_seeds 보존 (yaml ≠ None → DB 동일)
  - 위상정렬 정확성 (parent가 항상 child보다 먼저)
  - circular reference 감지

실행:
    cd packages/db-admin/backend
    py -3 -m pytest tests/test_categories_seed.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_BACKEND = _ROOT / "packages" / "db-admin" / "backend"
_SHARED = _ROOT / "packages" / "shared"
for p in (_BACKEND, _SHARED):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from storage.models import Base, Category

# ── YAML 경로 ─────────────────────────────────────────────────────────────────
_YAML_PATH = _SHARED / "data" / "categories_rd8.yaml"


# ════════════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def yaml_nodes() -> list[dict]:
    """YAML 원본 노드 목록."""
    with _YAML_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["categories"]


@pytest.fixture(scope="module")
def engine():
    """SQLite in-memory DB, Base.metadata 전체 스키마."""
    eng = create_engine("sqlite://", echo=False)
    # SQLite foreign_keys 활성화
    @event.listens_for(eng, "connect")
    def _set_fk(conn, _rec):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture(scope="module")
def seeded_session(engine, yaml_nodes) -> Session:
    """카테고리 265건 시드된 세션 (module scope — 한 번만 시드)."""
    # 인라인 import (tools/ 에 있으므로 sys.path 주의)
    _TOOLS = _ROOT / "tools"
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    from rd8_seed_categories import _topological_sort, upsert_categories

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    sorted_nodes = _topological_sort(yaml_nodes)
    upsert_categories(session, sorted_nodes, commit=True)
    yield session
    session.close()


# ════════════════════════════════════════════════════════════════════════════════
# 테스트 1: dry-run 카운트 일치
# ════════════════════════════════════════════════════════════════════════════════

def test_yaml_node_count(yaml_nodes: list[dict]) -> None:
    """YAML에 265개 노드가 있어야 한다."""
    assert len(yaml_nodes) == 265, f"기대 265, 실제 {len(yaml_nodes)}"


def test_seed_count(seeded_session: Session) -> None:
    """시드 후 DB에 정확히 265개 카테고리(source=rd8_seed)가 있어야 한다."""
    count = seeded_session.query(Category).filter(
        Category.source == "rd8_seed"
    ).count()
    assert count == 265, f"기대 265, 실제 {count}"


def test_leaf_count(seeded_session: Session) -> None:
    """leaf 카운트가 219여야 한다."""
    all_cats = seeded_session.query(Category).all()
    all_ids = {c.id for c in all_cats}
    parent_ids = {c.parent_id for c in all_cats if c.parent_id}
    leaves = all_ids - parent_ids
    assert len(leaves) == 219, f"기대 leaf=219, 실제 {len(leaves)}"


# ════════════════════════════════════════════════════════════════════════════════
# 테스트 2: parent 무결성
# ════════════════════════════════════════════════════════════════════════════════

def test_parent_integrity(seeded_session: Session) -> None:
    """child.parent_id가 DB에 있는 category.id를 참조해야 한다."""
    all_ids = {c.id for c in seeded_session.query(Category).all()}
    orphans = [
        c.id
        for c in seeded_session.query(Category).filter(Category.parent_id.isnot(None)).all()
        if c.parent_id not in all_ids
    ]
    assert orphans == [], f"고아 카테고리 발견: {orphans}"


def test_no_self_reference(seeded_session: Session) -> None:
    """어떤 카테고리도 자기 자신을 parent로 참조하지 않아야 한다."""
    self_refs = [
        c.id
        for c in seeded_session.query(Category).filter(Category.parent_id.isnot(None)).all()
        if c.id == c.parent_id
    ]
    assert self_refs == [], f"자기참조 카테고리 발견: {self_refs}"


# ════════════════════════════════════════════════════════════════════════════════
# 테스트 3: keyword_seeds 보존
# ════════════════════════════════════════════════════════════════════════════════

def test_keyword_seeds_preserved(seeded_session: Session, yaml_nodes: list[dict]) -> None:
    """yaml의 keyword_seeds가 DB에 그대로 보존돼야 한다."""
    import json
    errors = []
    for node in yaml_nodes:
        node_id = node["id"]
        expected_seeds = node.get("keyword_seeds") or []
        if not expected_seeds:
            continue  # 빈 keyword_seeds는 검사 생략
        cat = seeded_session.get(Category, node_id)
        if cat is None:
            errors.append(f"{node_id}: DB에 없음")
            continue
        actual = cat.keyword_seeds or []
        if json.dumps(actual, ensure_ascii=False, sort_keys=False) != \
           json.dumps(expected_seeds, ensure_ascii=False, sort_keys=False):
            errors.append(
                f"{node_id}: expected={expected_seeds[:3]}..., "
                f"actual={actual[:3]}..."
            )
    assert errors == [], f"keyword_seeds 불일치 {len(errors)}건:\n" + "\n".join(errors[:5])


# ════════════════════════════════════════════════════════════════════════════════
# 테스트 4: 위상정렬 정확성
# ════════════════════════════════════════════════════════════════════════════════

def test_topological_sort_order(yaml_nodes: list[dict]) -> None:
    """위상정렬 결과에서 parent가 항상 child보다 앞에 나타나야 한다."""
    _TOOLS = _ROOT / "tools"
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    from rd8_seed_categories import _topological_sort

    sorted_nodes = _topological_sort(yaml_nodes)
    seen_ids: set[str] = set()
    violations = []
    for node in sorted_nodes:
        parent = node.get("parent")
        if parent and parent not in seen_ids:
            violations.append(f"{node['id']}: parent={parent} 아직 미처리")
        seen_ids.add(node["id"])
    assert violations == [], f"위상정렬 위반 {len(violations)}건:\n" + "\n".join(violations[:5])


# ════════════════════════════════════════════════════════════════════════════════
# 테스트 5: circular reference 감지
# ════════════════════════════════════════════════════════════════════════════════

def test_circular_reference_detection(yaml_nodes: list[dict]) -> None:
    """순환 참조가 있으면 _topological_sort가 ValueError를 발생시켜야 한다."""
    _TOOLS = _ROOT / "tools"
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    from rd8_seed_categories import _topological_sort

    # 인위적 circular reference 주입
    circular_nodes = list(yaml_nodes) + [
        {"id": "test.circular.a", "display_name_ko": "A", "parent": "test.circular.b",
         "unit_kind_default": "count", "keyword_seeds": []},
        {"id": "test.circular.b", "display_name_ko": "B", "parent": "test.circular.a",
         "unit_kind_default": "count", "keyword_seeds": []},
    ]
    with pytest.raises(ValueError, match="circular reference"):
        _topological_sort(circular_nodes)


# ════════════════════════════════════════════════════════════════════════════════
# 테스트 6: 멱등성 (2회 시드 — unchanged만)
# ════════════════════════════════════════════════════════════════════════════════

def test_idempotent_reseed(engine, yaml_nodes: list[dict]) -> None:
    """같은 YAML로 2번 시드하면 2번째는 unchanged=265여야 한다."""
    _TOOLS = _ROOT / "tools"
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    from rd8_seed_categories import _topological_sort, upsert_categories

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    sorted_nodes = _topological_sort(yaml_nodes)
    stats = upsert_categories(session, sorted_nodes, commit=True)
    # 이미 seeded_session fixture에서 1회 적재됨 → 2번째는 unchanged=265
    assert stats["created"] == 0, f"2번째 시드에서 created={stats['created']} (기대 0)"
    assert stats["updated"] == 0, f"2번째 시드에서 updated={stats['updated']} (기대 0)"
    assert stats["unchanged"] == 265, f"2번째 시드 unchanged={stats['unchanged']} (기대 265)"
    session.close()
