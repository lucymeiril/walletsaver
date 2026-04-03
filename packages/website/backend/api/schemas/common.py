"""공통 응답 스키마"""
from pydantic import BaseModel
from typing import Optional, Any


class PaginationMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    error: Optional[str] = None
    meta: Optional[PaginationMeta] = None
