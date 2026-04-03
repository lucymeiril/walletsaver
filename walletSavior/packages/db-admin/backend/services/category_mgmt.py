"""카테고리 관리 서비스 — CRUD + 트리 구조 관리"""
from __future__ import annotations

from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from storage.models import Category, Product


def get_category_tree(session: Session) -> list[dict]:
    """전체 카테고리 트리 반환 (product_count 포함)"""
    categories = session.execute(
        select(Category).where(Category.is_active == True).order_by(Category.sort_order)
    ).scalars().all()

    # 카테고리별 직접 소속 상품 수 집계
    product_counts = dict(
        session.execute(
            select(Product.category_id, func.count(Product.id))
            .where(Product.is_active == True, Product.category_id.isnot(None))
            .group_by(Product.category_id)
        ).all()
    )

    by_id: dict[str, dict] = {}
    for cat in categories:
        by_id[cat.id] = {
            "id": cat.id,
            "name": cat.name,
            "parent_id": cat.parent_id,
            "depth": cat.depth,
            "icon": cat.icon,
            "attributes": cat.attributes,
            "productCount": product_counts.get(cat.id, 0),
            "children": [],
        }

    roots: list[dict] = []
    for node in by_id.values():
        pid = node["parent_id"]
        if pid and pid in by_id:
            by_id[pid]["children"].append(node)
        else:
            roots.append(node)
    return roots


def get_category(session: Session, category_id: str) -> Optional[dict]:
    """단일 카테고리 + 하위 카테고리"""
    cat = session.get(Category, category_id)
    if not cat:
        return None

    children = session.execute(
        select(Category).where(
            Category.parent_id == category_id,
            Category.is_active == True,
        ).order_by(Category.sort_order)
    ).scalars().all()

    return {
        "id": cat.id,
        "name": cat.name,
        "parent_id": cat.parent_id,
        "depth": cat.depth,
        "icon": cat.icon,
        "attributes": cat.attributes,
        "children": [
            {"id": c.id, "name": c.name, "depth": c.depth}
            for c in children
        ],
    }


def create_category(
    session: Session,
    category_id: str,
    name: str,
    parent_id: Optional[str] = None,
    attributes: Optional[dict] = None,
    icon: Optional[str] = None,
    sort_order: int = 0,
) -> dict:
    """카테고리 추가"""
    depth = 0
    if parent_id:
        parent = session.get(Category, parent_id)
        if parent:
            depth = parent.depth + 1

    cat = Category(
        id=category_id,
        name=name,
        parent_id=parent_id,
        depth=depth,
        sort_order=sort_order,
        icon=icon,
        attributes=attributes,
        is_active=True,
    )
    session.add(cat)
    session.commit()
    session.refresh(cat)
    return {
        "id": cat.id,
        "name": cat.name,
        "parent_id": cat.parent_id,
        "depth": cat.depth,
    }


def update_category(session: Session, category_id: str, data: dict) -> Optional[dict]:
    """카테고리 수정"""
    cat = session.get(Category, category_id)
    if not cat:
        return None

    for key in ("name", "icon", "sort_order", "attributes", "is_active"):
        if key in data:
            setattr(cat, key, data[key])

    session.commit()
    session.refresh(cat)
    return {
        "id": cat.id,
        "name": cat.name,
        "parent_id": cat.parent_id,
        "depth": cat.depth,
        "icon": cat.icon,
    }


def delete_category(session: Session, category_id: str) -> bool:
    """카테고리 삭제 (하위 카테고리는 부모를 현재 카테고리의 부모로 변경)"""
    cat = session.get(Category, category_id)
    if not cat:
        return False

    children = session.execute(
        select(Category).where(Category.parent_id == category_id)
    ).scalars().all()
    for child in children:
        child.parent_id = cat.parent_id
        if cat.parent_id:
            child.depth = cat.depth
        else:
            child.depth = 0

    # 소속 상품의 category_id를 None으로
    products = session.execute(
        select(Product).where(Product.category_id == category_id)
    ).scalars().all()
    for p in products:
        p.category_id = None

    session.delete(cat)
    session.commit()
    return True


def get_category_products(session: Session, category_id: str) -> list[dict]:
    """카테고리 소속 상품 목록"""
    products = session.execute(
        select(Product).where(
            Product.category_id == category_id,
            Product.is_active == True,
        )
    ).scalars().all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "unit": p.unit,
            "category_id": p.category_id,
        }
        for p in products
    ]


def get_category_product_count(session: Session, category_id: str) -> int:
    """카테고리 소속 상품 수"""
    count = session.execute(
        select(func.count(Product.id)).where(
            Product.category_id == category_id,
            Product.is_active == True,
        )
    ).scalar()
    return count or 0


def move_category(
    session: Session, category_id: str, new_parent_id: Optional[str]
) -> Optional[dict]:
    """카테고리 부모 변경 (이동)"""
    cat = session.get(Category, category_id)
    if not cat:
        return None

    # 자기 자신을 부모로 설정 불가
    if new_parent_id == category_id:
        return None

    # 순환 참조 방지: new_parent가 category_id의 하위인지 확인
    if new_parent_id:
        parent = session.get(Category, new_parent_id)
        if not parent:
            return None
        # 상위 체인을 따라가며 순환 확인
        check_id = new_parent_id
        while check_id:
            if check_id == category_id:
                return None
            check_cat = session.get(Category, check_id)
            check_id = check_cat.parent_id if check_cat else None

    # 부모 변경
    cat.parent_id = new_parent_id

    # depth 재계산
    if new_parent_id:
        new_parent = session.get(Category, new_parent_id)
        cat.depth = (new_parent.depth + 1) if new_parent else 0
    else:
        cat.depth = 0

    # 하위 카테고리 depth도 재귀적으로 갱신
    _update_children_depth(session, cat)

    session.commit()
    session.refresh(cat)
    return {
        "id": cat.id,
        "name": cat.name,
        "parent_id": cat.parent_id,
        "depth": cat.depth,
    }


def _update_children_depth(session: Session, parent: Category) -> None:
    """하위 카테고리 depth 재귀 갱신"""
    children = session.execute(
        select(Category).where(Category.parent_id == parent.id)
    ).scalars().all()
    for child in children:
        child.depth = parent.depth + 1
        _update_children_depth(session, child)
