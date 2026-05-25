"""rd8_seed_categories.py — RD8 C4 카테고리 시드 적재 스크립트.

사용법:
    py -3 tools/rd8_seed_categories.py --yaml packages/shared/data/categories_rd8.yaml
        → dry-run: 변경 내역 출력, DB 미반영

    py -3 tools/rd8_seed_categories.py --yaml packages/shared/data/categories_rd8.yaml --commit
        → DB 실제 UPSERT 반영

보장:
    - parent 먼저, child 나중에 (위상정렬 순서 INSERT)
    - 멱등성: 같은 파일을 2번 실행해도 결과 동일 (UPSERT by id)
    - dry-run과 --commit의 통계 숫자는 항상 일치
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "packages" / "db-admin" / "backend"
_SHARED = _ROOT / "packages" / "shared"
for p in (_BACKEND, _SHARED):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Base, Category

# ── DB URL (환경변수 우선, 없으면 walletguardian.db) ────────────────────────
_DB_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{_BACKEND / 'walletguardian.db'}",
)

# ── unit_kind 허용값 ──────────────────────────────────────────────────────────
_VALID_UNIT_KINDS = frozenset({"weight", "volume", "count", "pack"})

# ── source 고정값 ─────────────────────────────────────────────────────────────
_SOURCE = "rd8_seed"


# ════════════════════════════════════════════════════════════════════════════════
# 위상정렬 (parent 먼저)
# ════════════════════════════════════════════════════════════════════════════════

def _topological_sort(nodes: list[dict]) -> list[dict]:
    """parent가 항상 child보다 먼저 오도록 위상정렬.

    circular reference 감지: 무한루프 방지를 위해 방문 집합 추적.
    """
    id_map: dict[str, dict] = {n["id"]: n for n in nodes}
    order: list[dict] = []
    visited: set[str] = set()

    def _visit(node_id: str, ancestors: set[str]) -> None:
        if node_id in ancestors:
            raise ValueError(f"circular reference detected: {node_id}")
        if node_id in visited:
            return
        ancestors = ancestors | {node_id}
        parent = id_map[node_id].get("parent")
        if parent and parent in id_map:
            _visit(parent, ancestors)
        visited.add(node_id)
        order.append(id_map[node_id])

    for n in nodes:
        _visit(n["id"], set())

    return order


# ════════════════════════════════════════════════════════════════════════════════
# YAML 파싱
# ════════════════════════════════════════════════════════════════════════════════

def load_yaml(yaml_path: Path) -> list[dict]:
    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    nodes: list[dict] = data.get("categories", [])
    if not nodes:
        raise ValueError(f"yaml에 'categories' 키가 없거나 비어 있음: {yaml_path}")
    return nodes


# ════════════════════════════════════════════════════════════════════════════════
# 단일 노드 → Category 딕셔너리 변환
# ════════════════════════════════════════════════════════════════════════════════

def _node_to_fields(node: dict, now: datetime) -> dict[str, Any]:
    unit_kind = node.get("unit_kind_default")
    if unit_kind and unit_kind not in _VALID_UNIT_KINDS:
        raise ValueError(
            f"[{node['id']}] unit_kind_default 허용값: {sorted(_VALID_UNIT_KINDS)}, "
            f"받은 값: {unit_kind!r}"
        )
    keyword_seeds = node.get("keyword_seeds") or []
    display_name_ko = node.get("display_name_ko") or ""
    return {
        "id": node["id"],
        "name": display_name_ko or node["id"],  # 레거시 name 컬럼 호환
        "parent_id": node.get("parent") or None,
        "display_name_ko": display_name_ko or None,
        "unit_kind_default": unit_kind or None,
        "keyword_seeds": keyword_seeds if keyword_seeds else [],
        "notes": node.get("notes") or None,
        "source": _SOURCE,
        "is_active": True,
        "depth": len(node["id"].split(".")) - 1,
        "created_at": now,
        "updated_at": now,
    }


# ════════════════════════════════════════════════════════════════════════════════
# UPSERT 로직
# ════════════════════════════════════════════════════════════════════════════════

def _fields_changed(existing: Category, fields: dict[str, Any]) -> bool:
    """기존 Category 객체와 새 필드 비교 — 변경 여부 반환."""
    check_keys = [
        "name", "parent_id", "display_name_ko", "unit_kind_default",
        "keyword_seeds", "notes", "source", "is_active",
    ]
    for k in check_keys:
        existing_val = getattr(existing, k, None)
        new_val = fields.get(k)
        # JSON list 비교
        if isinstance(existing_val, (list, dict)) or isinstance(new_val, (list, dict)):
            if json.dumps(existing_val, ensure_ascii=False, sort_keys=True) != \
               json.dumps(new_val, ensure_ascii=False, sort_keys=True):
                return True
        elif existing_val != new_val:
            return True
    return False


def upsert_categories(
    session: Session,
    sorted_nodes: list[dict],
    commit: bool,
) -> dict[str, int]:
    """위상정렬된 노드 목록을 UPSERT.

    Returns: {'created': N, 'updated': N, 'unchanged': N}
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # SQLite naive datetime
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    created_ids: set[str] = set()

    for node in sorted_nodes:
        fields = _node_to_fields(node, now)
        node_id = fields["id"]
        existing = session.get(Category, node_id)

        if existing is None:
            new_cat = Category(**fields)
            session.add(new_cat)
            stats["created"] += 1
            created_ids.add(node_id)
        else:
            if _fields_changed(existing, fields):
                for k, v in fields.items():
                    if k not in ("id", "created_at"):
                        setattr(existing, k, v)
                existing.updated_at = now
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1

    if commit:
        session.commit()
    else:
        session.flush()  # 제약조건 검사만 (rollback은 호출자 책임)

    return stats


# ════════════════════════════════════════════════════════════════════════════════
# 검증
# ════════════════════════════════════════════════════════════════════════════════

def verify_integrity(session: Session) -> dict[str, Any]:
    """적재 후 무결성 검증:
    - rd8_seed 총 카운트 (= 265 기대)
    - leaf 카운트 (= 219 기대)
    - parent 참조 무결성 (고아 child 없음)
    - circular 자기참조 없음 (id == parent_id)
    """
    # rd8_seed 소스만 대상 (DB 내 다른 카테고리 제외)
    rd8_cats = session.query(Category).filter(Category.source == "rd8_seed").all()
    rd8_ids = {c.id for c in rd8_cats}
    total = len(rd8_ids)

    # leaf: rd8 카테고리 중 다른 rd8 카테고리의 parent가 아닌 것
    parent_ids_in_rd8 = {
        c.parent_id for c in rd8_cats if c.parent_id and c.parent_id in rd8_ids
    }
    leaves = len(rd8_ids - parent_ids_in_rd8)

    # 고아: parent_id가 있는데 DB 전체에 없는 경우
    all_db_ids = {c.id for c in session.query(Category).all()}
    orphans = [
        c.id for c in rd8_cats
        if c.parent_id and c.parent_id not in all_db_ids
    ]
    self_refs = [c.id for c in rd8_cats if c.id == c.parent_id]

    return {
        "total": total,
        "leaf_count": leaves,
        "orphan_count": len(orphans),
        "orphan_ids": orphans[:10],
        "self_ref_count": len(self_refs),
        "self_ref_ids": self_refs,
    }


# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RD8 C4 카테고리 YAML → DB UPSERT"
    )
    parser.add_argument(
        "--yaml",
        default="packages/shared/data/categories_rd8.yaml",
        help="입력 YAML 경로 (default: packages/shared/data/categories_rd8.yaml)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="지정하지 않으면 dry-run (롤백)",
    )
    args = parser.parse_args()

    yaml_path = Path(args.yaml).resolve()
    if not yaml_path.exists():
        print(f"[ERROR] YAML 파일 없음: {yaml_path}")
        sys.exit(1)

    print(f"[INFO] YAML 경로 : {yaml_path}")
    print(f"[INFO] DB URL    : {_DB_URL}")
    print(f"[INFO] 모드      : {'--commit (실제 반영)' if args.commit else 'dry-run (롤백)'}")
    print()

    # ── 노드 파싱 & 위상정렬 ─────────────────────────────────────────────────
    nodes = load_yaml(yaml_path)
    print(f"[YAML] 파싱된 노드 수: {len(nodes)}")
    sorted_nodes = _topological_sort(nodes)
    print(f"[YAML] 위상정렬 완료: {len(sorted_nodes)} 노드")

    # ── DB 연결 ───────────────────────────────────────────────────────────────
    engine = create_engine(
        _DB_URL,
        connect_args={"check_same_thread": False} if "sqlite" in _DB_URL else {},
    )
    # SQLite WAL 모드 활성화 (concurrency 향상)
    if "sqlite" in _DB_URL:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA foreign_keys=ON"))

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        stats = upsert_categories(session, sorted_nodes, commit=args.commit)

        if not args.commit:
            session.rollback()

        print()
        print("╔══════════════════════════════╗")
        print(f"║ {'dry-run 결과' if not args.commit else '적재 결과':^28} ║")
        print("╠══════════════════════════════╣")
        print(f"║  created   : {stats['created']:>14}  ║")
        print(f"║  updated   : {stats['updated']:>14}  ║")
        print(f"║  unchanged : {stats['unchanged']:>14}  ║")
        print(f"║  합계      : {sum(stats.values()):>14}  ║")
        print("╚══════════════════════════════╝")

        if args.commit:
            print()
            print("[검증] 적재 후 무결성 검사:")
            v = verify_integrity(session)
            print(f"  총 categories : {v['total']}")
            print(f"  leaf 카운트   : {v['leaf_count']}")
            print(f"  고아 노드     : {v['orphan_count']} (기대: 0)")
            print(f"  자기참조      : {v['self_ref_count']} (기대: 0)")
            if v["orphan_ids"]:
                print(f"  [WARN] 고아 IDs: {v['orphan_ids']}")
            if v["self_ref_ids"]:
                print(f"  [WARN] 자기참조 IDs: {v['self_ref_ids']}")
            total_ok = v["total"] == 265
            leaf_ok = v["leaf_count"] == 219
            integrity_ok = v["orphan_count"] == 0 and v["self_ref_count"] == 0
            print()
            if total_ok and leaf_ok and integrity_ok:
                print("[OK] 검증 통과: COUNT=265, leaf=219, integrity=OK")
            else:
                print(f"[WARN] 검증 실패: total={v['total']} (기대 265), leaf={v['leaf_count']} (기대 219)")

    except Exception as e:
        session.rollback()
        print(f"[ERROR] {e}")
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
