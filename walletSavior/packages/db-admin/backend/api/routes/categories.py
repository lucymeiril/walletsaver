"""카테고리 CRUD 라우트"""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from services.base import get_session
from services.audit import log_action
from api.auth import require_viewer, require_moderator, require_admin
from services.category_mgmt import (
    get_category_tree,
    get_category,
    create_category,
    update_category,
    delete_category,
    get_category_products,
    get_category_product_count,
    move_category,
)

from api.security import MAX_CATEGORY_ID_LEN, MAX_NAME_LEN, MAX_ICON_LEN

_CATEGORY_ID_RE = __import__("re").compile(r"^[a-z0-9]+(\.[a-z0-9]+)*$")

router = APIRouter(prefix="/categories", tags=["categories"])


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
            raise ValueError("카테고리 ID는 소문자 영숫자와 점(.)으로 구성해야 합니다.")
        return v


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_NAME_LEN)
    icon: Optional[str] = Field(None, max_length=MAX_ICON_LEN)
    sort_order: Optional[int] = Field(None, ge=0, le=9999)
    attributes: Optional[dict] = None
    is_active: Optional[bool] = None


class CategoryMove(BaseModel):
    new_parent_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)


@router.get("/")
def list_categories(identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return get_category_tree(session)
    finally:
        session.close()


@router.get("/{category_id}")
def read_category(category_id: str, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        result = get_category(session, category_id)
        if not result:
            raise HTTPException(404, "Category not found")
        return result
    finally:
        session.close()


@router.post("/", status_code=201)
def add_category(body: CategoryCreate, identity: dict = Depends(require_moderator)):
    session = get_session()
    try:
        return create_category(
            session, body.id, body.name, body.parent_id,
            body.attributes, body.icon, body.sort_order,
        )
    finally:
        session.close()


@router.put("/{category_id}")
def modify_category(category_id: str, body: CategoryUpdate, identity: dict = Depends(require_moderator)):
    session = get_session()
    try:
        result = update_category(session, category_id, body.model_dump(exclude_unset=True))
        if not result:
            raise HTTPException(404, "Category not found")
        return result
    finally:
        session.close()


@router.delete("/{category_id}")
def remove_category(category_id: str, identity: dict = Depends(require_admin)):
    session = get_session()
    try:
        ok = delete_category(session, category_id)
        if not ok:
            raise HTTPException(404, "Category not found")
        return {"deleted": True}
    finally:
        session.close()


@router.get("/{category_id}/products")
def category_products(category_id: str, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return get_category_products(session, category_id)
    finally:
        session.close()


@router.get("/{category_id}/product-count")
def category_product_count(category_id: str, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        count = get_category_product_count(session, category_id)
        return {"category_id": category_id, "product_count": count}
    finally:
        session.close()


@router.put("/{category_id}/move")
def move_cat(category_id: str, body: CategoryMove, identity: dict = Depends(require_moderator)):
    session = get_session()
    try:
        result = move_category(session, category_id, body.new_parent_id)
        if not result:
            raise HTTPException(400, "이동 실패: 대상을 찾을 수 없거나 순환 참조가 발생합니다")
        return result
    finally:
        session.close()
