"""정본 카탈로그 데이터 불변식(invariant) 검증.

Phase 0의 안전망이자 Phase 1/2 import apply 전 사전검증으로 재사용된다.

검증 대상(정본):
  - unified_categories 트리: 고아 parent, 사이클, level 정합, 최대 깊이
  - mart_category_mappings: unified FK 존재, (mart, mart_native_id) 유일
  - products.unified_category_id: 존재하는 카테고리 참조

검증기는 절대 raise하지 않는다. 발견한 문제를 issue 리스트로 모아 반환한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from storage.models import MartCategoryMapping, Product, UnifiedCategory

MAX_TREE_DEPTH = 2  # level 0,1,2 = 3단계


@dataclass
class InvariantIssue:
    entity: str          # "unified_categories" | "mart_category_mappings" | "products"
    code: str            # 기계 판독용 코드
    message: str         # 사람 판독용 설명
    sample: list[Any] = field(default_factory=list)
    count: int = 0


@dataclass
class InvariantReport:
    issues: list[InvariantIssue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return len(self.issues) == 0

    def add(self, issue: InvariantIssue) -> None:
        if issue.count:
            self.issues.append(issue)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": self.counts,
            "issues": [
                {
                    "entity": i.entity,
                    "code": i.code,
                    "message": i.message,
                    "count": i.count,
                    "sample": i.sample[:20],
                }
                for i in self.issues
            ],
        }


def _check_unified_tree(session: Session, report: InvariantReport) -> None:
    categories = session.scalars(select(UnifiedCategory)).all()
    report.counts["unified_categories"] = len(categories)
    by_id = {c.id: c for c in categories}

    # 고아 parent
    orphans = [c.id for c in categories if c.parent_id is not None and c.parent_id not in by_id]
    report.add(InvariantIssue(
        "unified_categories", "orphan_parent",
        "존재하지 않는 parent_id를 가리키는 카테고리", sample=orphans, count=len(orphans),
    ))

    # 사이클: parent 체인을 따라가다 자기 자신/방문노드 재방문
    cyclic: list[str] = []
    for c in categories:
        seen: set[str] = set()
        cur = c
        while cur is not None and cur.parent_id is not None:
            if cur.id in seen:
                cyclic.append(c.id)
                break
            seen.add(cur.id)
            cur = by_id.get(cur.parent_id)
            if cur is None:  # 고아는 위에서 별도 보고
                break
    report.add(InvariantIssue(
        "unified_categories", "cycle",
        "parent 체인에 사이클이 있는 카테고리", sample=cyclic, count=len(cyclic),
    ))

    # level 정합: root는 level 0, 자식은 parent.level+1
    level_mismatch: list[str] = []
    for c in categories:
        if c.parent_id is None:
            if c.level != 0:
                level_mismatch.append(c.id)
        else:
            parent = by_id.get(c.parent_id)
            if parent is not None and c.level != parent.level + 1:
                level_mismatch.append(c.id)
    report.add(InvariantIssue(
        "unified_categories", "level_mismatch",
        "level이 부모 깊이와 맞지 않는 카테고리", sample=level_mismatch, count=len(level_mismatch),
    ))

    # 최대 깊이 초과
    too_deep = [c.id for c in categories if c.level > MAX_TREE_DEPTH]
    report.add(InvariantIssue(
        "unified_categories", "depth_exceeded",
        f"최대 깊이({MAX_TREE_DEPTH})를 초과한 카테고리", sample=too_deep, count=len(too_deep),
    ))


def _check_mappings(session: Session, report: InvariantReport) -> None:
    total = session.scalar(select(func.count()).select_from(MartCategoryMapping)) or 0
    report.counts["mart_category_mappings"] = int(total)

    missing = session.scalars(
        select(MartCategoryMapping.id).where(
            ~MartCategoryMapping.unified_category_id.in_(select(UnifiedCategory.id))
        )
    ).all()
    report.add(InvariantIssue(
        "mart_category_mappings", "dangling_unified",
        "존재하지 않는 unified_category_id를 가리키는 매핑", sample=list(missing), count=len(missing),
    ))

    dup_rows = session.execute(
        select(MartCategoryMapping.mart, MartCategoryMapping.mart_native_id)
        .group_by(MartCategoryMapping.mart, MartCategoryMapping.mart_native_id)
        .having(func.count() > 1)
    ).all()
    report.add(InvariantIssue(
        "mart_category_mappings", "duplicate_native",
        "(mart, mart_native_id) 중복 매핑", sample=[f"{m}:{n}" for m, n in dup_rows], count=len(dup_rows),
    ))


def _check_products(session: Session, report: InvariantReport) -> None:
    total = session.scalar(select(func.count()).select_from(Product)) or 0
    report.counts["products"] = int(total)

    dangling = session.scalars(
        select(Product.id).where(
            Product.unified_category_id.is_not(None),
            ~Product.unified_category_id.in_(select(UnifiedCategory.id)),
        )
    ).all()
    report.add(InvariantIssue(
        "products", "dangling_unified",
        "존재하지 않는 unified_category_id를 가리키는 상품", sample=list(dangling), count=len(dangling),
    ))

    unclassified = session.scalar(
        select(func.count()).select_from(Product).where(Product.unified_category_id.is_(None))
    ) or 0
    report.counts["products_unclassified"] = int(unclassified)


def check_invariants(session: Session) -> InvariantReport:
    """정본 데이터 전체 불변식을 점검해 리포트를 반환한다(raise 없음)."""
    report = InvariantReport()
    _check_unified_tree(session, report)
    _check_mappings(session, report)
    _check_products(session, report)
    return report
