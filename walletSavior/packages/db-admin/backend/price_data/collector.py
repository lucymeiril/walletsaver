"""
가격 데이터 수집기 — CSV/JSON 임포트, KAMIS 파서, 마트 데이터 집계.

외부 데이터 소스에서 가격 데이터를 수집하고 정규화하는 인터페이스를 제공한다.
실제 DB 의존성 없이 순수 데이터 변환 로직만 포함.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Optional


class PriceRecord:
    """정규화된 가격 레코드."""

    __slots__ = (
        "product_id", "product_name", "price", "original_price",
        "source", "unit", "recorded_at", "raw_data",
    )

    def __init__(
        self,
        product_id: int,
        product_name: str,
        price: float,
        source: str,
        unit: str = "",
        original_price: Optional[float] = None,
        recorded_at: Optional[datetime] = None,
        raw_data: Optional[dict] = None,
    ):
        self.product_id = product_id
        self.product_name = product_name
        self.price = price
        self.original_price = original_price
        self.source = source
        self.unit = unit
        self.recorded_at = recorded_at or datetime.now()
        self.raw_data = raw_data

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "price": self.price,
            "original_price": self.original_price,
            "source": self.source,
            "unit": self.unit,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "raw_data": self.raw_data,
        }

    def is_valid(self) -> bool:
        return (
            self.product_id > 0
            and len(self.product_name.strip()) > 0
            and self.price > 0
            and len(self.source.strip()) > 0
        )


class ValidationResult:
    """데이터 검증 결과."""

    def __init__(self):
        self.valid: list[PriceRecord] = []
        self.invalid: list[dict] = []
        self.total = 0

    @property
    def valid_count(self) -> int:
        return len(self.valid)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "valid": self.valid_count,
            "invalid": self.invalid_count,
            "errors": self.invalid,
        }


def validate_price_record(data: dict) -> tuple[Optional[PriceRecord], list[str]]:
    """단일 레코드 검증. (PriceRecord | None, errors)"""
    errors: list[str] = []

    product_id = data.get("product_id")
    if product_id is None:
        errors.append("product_id 누락")
    elif not isinstance(product_id, (int, float)) or product_id <= 0:
        errors.append("product_id는 양의 정수여야 합니다")

    product_name = data.get("product_name", "")
    if not product_name or not str(product_name).strip():
        errors.append("product_name 누락")

    price = data.get("price")
    if price is None:
        errors.append("price 누락")
    elif not isinstance(price, (int, float)):
        errors.append("price는 숫자여야 합니다")
    elif price <= 0:
        errors.append("price는 0보다 커야 합니다")

    source = data.get("source", "")
    if not source or not str(source).strip():
        errors.append("source 누락")

    if errors:
        return None, errors

    recorded_at = data.get("recorded_at")
    if isinstance(recorded_at, str):
        try:
            recorded_at = datetime.fromisoformat(recorded_at)
        except ValueError:
            errors.append("recorded_at 형식 오류 (ISO 8601 필요)")
            recorded_at = None

    return PriceRecord(
        product_id=int(product_id),
        product_name=str(product_name).strip(),
        price=float(price),
        original_price=float(data["original_price"]) if data.get("original_price") else None,
        source=str(source).strip(),
        unit=str(data.get("unit", "")),
        recorded_at=recorded_at if isinstance(recorded_at, datetime) else datetime.now(),
        raw_data=data.get("raw_data"),
    ), errors


def import_from_csv(csv_content: str, source: str = "csv_import") -> ValidationResult:
    """
    CSV 문자열에서 가격 데이터를 임포트한다.

    필수 컬럼: product_id, product_name, price
    선택 컬럼: source, unit, original_price, recorded_at
    """
    result = ValidationResult()
    reader = csv.DictReader(io.StringIO(csv_content))

    for i, row in enumerate(reader):
        result.total += 1
        data = dict(row)
        # CSV는 모두 문자열이므로 숫자 변환
        for key in ("product_id", "price", "original_price"):
            if key in data and data[key]:
                try:
                    data[key] = float(data[key])
                    if key == "product_id":
                        data[key] = int(data[key])
                except ValueError:
                    pass

        if not data.get("source"):
            data["source"] = source

        record, errors = validate_price_record(data)
        if record:
            result.valid.append(record)
        else:
            result.invalid.append({"row": i + 1, "data": row, "errors": errors})

    return result


def import_from_json(json_content: str, source: str = "json_import") -> ValidationResult:
    """
    JSON 문자열(배열)에서 가격 데이터를 임포트한다.

    각 요소: {"product_id", "product_name", "price", ...}
    """
    result = ValidationResult()

    try:
        items = json.loads(json_content)
    except json.JSONDecodeError as e:
        result.total = 0
        result.invalid.append({"row": 0, "errors": [f"JSON 파싱 오류: {e}"]})
        return result

    if not isinstance(items, list):
        items = [items]

    for i, data in enumerate(items):
        result.total += 1
        if not data.get("source"):
            data["source"] = source

        record, errors = validate_price_record(data)
        if record:
            result.valid.append(record)
        else:
            result.invalid.append({"row": i + 1, "data": data, "errors": errors})

    return result


def parse_kamis_data(raw_data: list[dict]) -> list[PriceRecord]:
    """
    KAMIS (농산물유통정보) 형식 데이터를 PriceRecord로 변환.

    KAMIS 응답 형식:
    {
        "item_name": "배추",
        "item_code": "211",
        "kind_name": "배추",
        "unit": "1포기",
        "day1": "3,200",   # 1일 전 가격
        "day2": "3,150",   # 2일 전 가격
        ...
        "dpr1": "3,200",   # 당일 소매 가격
        "dpr2": "3,150",   # 전일 소매 가격
    }
    """
    records: list[PriceRecord] = []

    for item in raw_data:
        item_name = item.get("item_name", "").strip()
        if not item_name:
            continue

        product_id = item.get("product_id", 0)
        unit = item.get("unit", "")

        # dpr1 ~ dpr7 파싱 (당일 ~ 7일 전)
        for day_offset, key in enumerate(["dpr1", "dpr2", "dpr3", "dpr5", "dpr7"]):
            raw_price = item.get(key, "")
            if not raw_price or raw_price == "-":
                continue

            try:
                price = float(str(raw_price).replace(",", ""))
                if price <= 0:
                    continue
            except (ValueError, TypeError):
                continue

            recorded_at = datetime.now()
            if day_offset > 0:
                from datetime import timedelta
                recorded_at = recorded_at - timedelta(days=day_offset)

            records.append(PriceRecord(
                product_id=product_id,
                product_name=item_name,
                price=price,
                source="kamis",
                unit=unit,
                recorded_at=recorded_at,
                raw_data=item,
            ))

    return records


def aggregate_mart_prices(
    crawl_results: list[dict],
    store_name: str,
) -> list[PriceRecord]:
    """
    크롤러 결과를 PriceRecord 리스트로 변환.

    crawl_results 형식:
    [{"name": "배추", "price": 3200, "original_price": 4000, "url": "..."}, ...]
    """
    records: list[PriceRecord] = []

    for item in crawl_results:
        name = item.get("name", "").strip()
        price = item.get("price")
        if not name or not price:
            continue

        try:
            price = float(price)
        except (ValueError, TypeError):
            continue

        if price <= 0:
            continue

        original = item.get("original_price")
        if original:
            try:
                original = float(original)
            except (ValueError, TypeError):
                original = None

        records.append(PriceRecord(
            product_id=item.get("product_id", 0),
            product_name=name,
            price=price,
            original_price=original,
            source=store_name,
            unit=item.get("unit", ""),
            recorded_at=datetime.now(),
            raw_data=item,
        ))

    return records


def batch_import(
    records: list[dict],
    source: str = "batch",
) -> ValidationResult:
    """
    딕셔너리 리스트를 일괄 검증하여 임포트한다.

    CSV/JSON 등 출처에 무관한 범용 배치 임포트.
    """
    result = ValidationResult()

    for i, data in enumerate(records):
        result.total += 1
        if not data.get("source"):
            data["source"] = source

        record, errors = validate_price_record(data)
        if record:
            result.valid.append(record)
        else:
            result.invalid.append({"row": i + 1, "data": data, "errors": errors})

    return result


def build_price_history(
    records: list[dict],
    product_id: int,
) -> list[dict]:
    """
    특정 제품의 가격 기록을 시간순으로 정렬하여 반환.

    Returns: [{"date": "YYYY-MM-DD", "price": float, "source": str}, ...]
    """
    filtered = [
        r for r in records
        if r.get("product_id") == product_id
    ]

    def _sort_key(r: dict):
        dt = r.get("recorded_at")
        if isinstance(dt, datetime):
            return dt
        if isinstance(dt, str):
            try:
                return datetime.fromisoformat(dt)
            except ValueError:
                pass
        return datetime.min

    filtered.sort(key=_sort_key)

    history: list[dict] = []
    for r in filtered:
        dt = r.get("recorded_at")
        if isinstance(dt, datetime):
            date_str = dt.strftime("%Y-%m-%d")
        elif isinstance(dt, str):
            date_str = dt[:10]
        else:
            date_str = ""

        history.append({
            "date": date_str,
            "price": r.get("price", 0),
            "source": r.get("source", ""),
        })

    return history
