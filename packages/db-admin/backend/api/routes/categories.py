"""카테고리 CRUD 라우트"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.base import get_session
from services.category_mgmt import (
    get_category_tree,
    get_category,
    create_category,
    update_category,
    delete_category,
    get_category_products,
)

router = APIRouter(prefix="/categories", tags=["categories"])


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


@router.get("/")
def list_categories():
    session = get_session()
    try:
        return get_category_tree(session)
    finally:
        session.close()


@router.get("/{category_id}")
def read_category(category_id: str):
    session = get_session()
    try:
        result = get_category(session, category_id)
        if not result:
            raise HTTPException(404, "Category not found")
        return result
    finally:
        session.close()


@router.post("/", status_code=201)
def add_category(body: CategoryCreate):
    session = get_session()
    try:
        return create_category(
            session, body.id, body.name, body.parent_id,
            body.attributes, body.icon, body.sort_order,
        )
    finally:
        session.close()


@router.put("/{category_id}")
def modify_category(category_id: str, body: CategoryUpdate):
    session = get_session()
    try:
        result = update_category(session, category_id, body.model_dump(exclude_unset=True))
        if not result:
            raise HTTPException(404, "Category not found")
        return result
    finally:
        session.close()


@router.delete("/{category_id}")
def remove_category(category_id: str):
    session = get_session()
    try:
        ok = delete_category(session, category_id)
        if not ok:
            raise HTTPException(404, "Category not found")
        return {"deleted": True}
    finally:
        session.close()


@router.get("/{category_id}/products")
def category_products(category_id: str):
    session = get_session()
    try:
        return get_category_products(session, category_id)
    finally:
        session.close()
