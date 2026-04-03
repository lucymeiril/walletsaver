"""분석 데이터 라우트"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from services.base import get_session
from services.data_quality import (
    check_price_outliers,
    find_duplicates,
    validate_crawl_data,
    generate_quality_report,
    cleanup_stale_data,
)
from services.export import (
    export_prices_csv,
    export_products_json,
    get_statistics_summary,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


class DuplicateRequest(BaseModel):
    table_name: str
    fields: list[str]


class ValidateRequest(BaseModel):
    items: list[dict]


@router.get("/outliers/{product_id}")
def outliers(product_id: int):
    session = get_session()
    try:
        return check_price_outliers(session, product_id)
    finally:
        session.close()


@router.post("/duplicates")
def duplicates(body: DuplicateRequest):
    session = get_session()
    try:
        return find_duplicates(session, body.table_name, body.fields)
    finally:
        session.close()


@router.post("/validate")
def validate(body: ValidateRequest):
    return validate_crawl_data(body.items)


@router.get("/quality-report")
def quality_report():
    session = get_session()
    try:
        return generate_quality_report(session)
    finally:
        session.close()


@router.post("/cleanup")
def cleanup(days: int = 180):
    session = get_session()
    try:
        return cleanup_stale_data(session, days)
    finally:
        session.close()


@router.get("/export/prices/{product_id}")
def export_prices(product_id: int, days: int = 30):
    session = get_session()
    try:
        csv_data = export_prices_csv(session, product_id, days)
        return {"csv": csv_data}
    finally:
        session.close()


@router.get("/export/products")
def export_products(category_id: Optional[str] = None):
    session = get_session()
    try:
        json_data = export_products_json(session, category_id)
        return {"json": json_data}
    finally:
        session.close()


@router.get("/summary")
def summary():
    session = get_session()
    try:
        return get_statistics_summary(session)
    finally:
        session.close()
