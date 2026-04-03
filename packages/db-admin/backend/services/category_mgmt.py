"""카테고리 관리 서비스 — CRUD + 트리 구조 관리"""
from __future__ import annotations

from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import Category, Product


def get_category_tree(session: Session) -> list[dict]:
    """전체 카테고리 트리 반환"""
    categories = session.execute(
        select(Category).where(Category.is_active == True).order_by(Category.sort_order)
    ).scalars().all()

    by_id: dict[str, dict] = {}
    for cat in categories:
        by_id[cat.id] = {
            "id": cat.id,
            "name": cat.name,
            "parent_id": cat.parent_id,
            "depth": cat.depth,
            "icon": cat.icon,
            "attributes": cat.attributes,
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
