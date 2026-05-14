"""
가격 아카이브 빌더 — 크롤링 데이터로부터 히스토리 아카이브를 구축한다.

제품별, 마트별, 기간별로 집계된 가격 추세 데이터를 생성하며,
제품×마트 비교 매트릭스도 제공한다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional


def _parse_date(dt) -> Optional[datetime]:
    if isinstance(dt, datetime):
        return dt
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt)
        except ValueError:
            return None
    return None


def _date_key(dt: datetime, period: str) -> str:
    """기간별 날짜 키 생성."""
    if period == "daily":
        return dt.strftime("%Y-%m-%d")
    elif period == "weekly":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    elif period == "monthly":
        return dt.strftime("%Y-%m")
    else:
        return dt.strftime("%Y-%m-%d")


def build_product_archive(
    records: list[dict],
    product_id: int,
) -> dict:
    """
    특정 제품의 전체 가격 아카이브를 구축한다.

    Returns: {
        "product_id": int,
        "total_records": int,
        "date_range": {"start": str, "end": str},
        "sources": ["emart", "homeplus", ...],
        "records": [{"date", "price", "source"}, ...],  # 시간순
    }
    """
    filtered = [
        r for r in records
        if r.get("product_id") == product_id and r.get("price", 0) > 0
    ]

    if not filtered:
        return {
            "product_id": product_id,
            "total_records": 0,
            "date_range": {"start": None, "end": None},
            "sources": [],
            "records": [],
        }

    dated: list[tuple[datetime, dict]] = []
    sources = set()
    for r in filtered:
        dt = _parse_date(r.get("recorded_at"))
        if dt:
            dated.append((dt, r))
        sources.add(r.get("source", "unknown"))

    dated.sort(key=lambda x: x[0])

    return {
        "product_id": product_id,
        "total_records": len(dated),
        "date_range": {
            "start": dated[0][0].strftime("%Y-%m-%d") if dated else None,
            "end": dated[-1][0].strftime("%Y-%m-%d") if dated else None,
        },
        "sources": sorted(sources),
        "records": [
            {
                "date": d.strftime("%Y-%m-%d"),
                "price": r.get("price"),
                "source": r.get("source", ""),
            }
            for d, r in dated
        ],
    }


def aggregate_by_period(
    records: list[dict],
    product_id: int,
    period: str = "daily",
) -> list[dict]:
    """
    제품의 가격을 기간별로 집계한다.

    period: "daily" | "weekly" | "monthly"

    Returns: [
        {"period": "2024-01-15", "avg_price": float, "min_price": float,
         "max_price": float, "count": int},
        ...
    ]
    """
    if period not in ("daily", "weekly", "monthly"):
        raise ValueError(f"지원하지 않는 기간: {period}. daily/weekly/monthly 중 선택")

    filtered = [
        r for r in records
        if r.get("product_id") == product_id and r.get("price", 0) > 0
    ]

    buckets: dict[str, list[float]] = defaultdict(list)
    for r in filtered:
        dt = _parse_date(r.get("recorded_at"))
        if not dt:
            continue
        key = _date_key(dt, period)
        buckets[key].append(r["price"])

    result = []
    for key in sorted(buckets.keys()):
        prices = buckets[key]
        result.append({
            "period": key,
            "avg_price": round(sum(prices) / len(prices), 1),
            "min_price": min(prices),
            "max_price": max(prices),
            "count": len(prices),
        })

    return result


def aggregate_by_store(
    records: list[dict],
    product_id: int,
) -> list[dict]:
    """
    제품의 마트별 가격 통계를 집계한다.

    Returns: [
        {"store": "emart", "avg_price": float, "min_price": float,
         "max_price": float, "count": int},
        ...
    ]
    """
    filtered = [
        r for r in records
        if r.get("product_id") == product_id and r.get("price", 0) > 0
    ]

    store_prices: dict[str, list[float]] = defaultdict(list)
    for r in filtered:
        store = r.get("source", "unknown")
        store_prices[store].append(r["price"])

    result = []
    for store in sorted(store_prices.keys()):
        prices = store_prices[store]
        result.append({
            "store": store,
            "avg_price": round(sum(prices) / len(prices), 1),
            "min_price": min(prices),
            "max_price": max(prices),
            "count": len(prices),
        })

    return result


def generate_price_trend(
    records: list[dict],
    product_id: int,
    period: str = "weekly",
) -> dict:
    """
    가격 추세 데이터를 생성한다 (차트용).

    Returns: {
        "product_id": int,
        "period": str,
        "data_points": [{"period": str, "avg_price": float}, ...],
        "overall_change_pct": float,
    }
    """
    agg = aggregate_by_period(records, product_id, period)

    if len(agg) >= 2:
        first_price = agg[0]["avg_price"]
        last_price = agg[-1]["avg_price"]
        if first_price > 0:
            change = ((last_price - first_price) / first_price) * 100
        else:
            change = 0
    else:
        change = 0

    return {
        "product_id": product_id,
        "period": period,
        "data_points": [{"period": a["period"], "avg_price": a["avg_price"]} for a in agg],
        "overall_change_pct": round(change, 2),
    }


def build_comparison_matrix(
    records: list[dict],
    product_ids: list[int],
) -> dict:
    """
    제품×마트 가격 비교 매트릭스를 생성한다.

    Returns: {
        "products": [id1, id2, ...],
        "stores": ["emart", "homeplus", ...],
        "matrix": {
            product_id: {
                "store_name": avg_price,
                ...
            },
            ...
        },
        "cheapest_store": {product_id: "store_name", ...},
    }
    """
    all_stores: set[str] = set()
    matrix: dict[int, dict[str, float]] = {}
    cheapest: dict[int, str] = {}

    for pid in product_ids:
        store_agg = aggregate_by_store(records, pid)
        store_dict: dict[str, float] = {}
        min_price = float("inf")
        min_store = ""

        for sa in store_agg:
            store = sa["store"]
            avg = sa["avg_price"]
            store_dict[store] = avg
            all_stores.add(store)
            if avg < min_price:
                min_price = avg
                min_store = store

        matrix[pid] = store_dict
        if min_store:
            cheapest[pid] = min_store

    return {
        "products": product_ids,
        "stores": sorted(all_stores),
        "matrix": matrix,
        "cheapest_store": cheapest,
    }


def build_full_archive(
    records: list[dict],
    product_ids: Optional[list[int]] = None,
) -> dict:
    """
    전체 가격 아카이브를 구축한다.

    사전 그룹핑으로 product_id 별 필터링 반복을 제거.
    """
    if product_ids is None:
        product_ids = sorted({r.get("product_id") for r in records if r.get("product_id")})

    # 사전 그룹핑 — O(n) 1회 스캔으로 product_id 별 레코드 분류
    grouped: dict[int, list[dict]] = defaultdict(list)
    for r in records:
        pid = r.get("product_id")
        if pid is not None:
            grouped[pid].append(r)

    products_data: dict[int, dict] = {}
    for pid in product_ids:
        pid_records = grouped.get(pid, [])
        products_data[pid] = {
            "archive": build_product_archive(pid_records, pid),
            "daily": aggregate_by_period(pid_records, pid, "daily"),
            "weekly": aggregate_by_period(pid_records, pid, "weekly"),
            "monthly": aggregate_by_period(pid_records, pid, "monthly"),
            "by_store": aggregate_by_store(pid_records, pid),
        }

    return {
        "generated_at": datetime.now().isoformat(),
        "total_records": len(records),
        "products": products_data,
        "comparison_matrix": build_comparison_matrix(records, product_ids),
    }
