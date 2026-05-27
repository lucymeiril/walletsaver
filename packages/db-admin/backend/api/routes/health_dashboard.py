"""RD8 F5 운영자 콘솔용 헬스 대시보드 라우트.

기존 라우트(dashboard, integrity, analytics)는 그대로 두고,
운영자가 "지금 DB 건강한가"를 한눈에 보기 위한 RD8-맞춤 뷰만 추가한다.

엔드포인트:
    GET  /api/health-dashboard/overview          오늘의 DB 상태 카드 + 마트별 분포 + 경고
    GET  /api/health-dashboard/products          카테고리 드릴다운 상품 리스트 (마트 뱃지 포함)
    GET  /api/health-dashboard/integrity         RD8 결함 카탈로그 기반 정합성 점검
    GET  /api/health-dashboard/matching-monitor  매칭 누적 모니터 (최근 7일)

스키마 가정:
    Product(name, source_type, category_id, attributes)
    BaselinePrice(product_id, source, price, recorded_at)  ← source가 mart_code 대용
    DiscountHistory(product_id, source, crawled_at)
    MatchingEntry(brand, name_core, pack_qty, pack_unit, source, canonical_product_id)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, or_, distinct, literal

from services.base import get_session
from api.auth import require_viewer
from api.source_normalization import normalize_source_key
from storage.models import (
    Product,
    BaselinePrice,
    DiscountHistory,
    HotdealPrice,
    Category,
    MatchingEntry,
    CrawlLog,
)

router = APIRouter(prefix="/health-dashboard", tags=["health-dashboard"])


# 운영자가 인지하는 마트 4사 (mart_code 후보)
KNOWN_MARTS = ("emart", "homeplus", "lottemart", "costco")


def _normalize(src: Optional[str]) -> Optional[str]:
    if not src:
        return None
    n = normalize_source_key(src)
    return n or src.strip().lower()


def _product_source_marts(session, product_id: int) -> list[str]:
    rows = (
        session.query(BaselinePrice.source)
        .filter(BaselinePrice.product_id == product_id)
        .distinct()
        .all()
    )
    rows2 = (
        session.query(DiscountHistory.source)
        .filter(DiscountHistory.product_id == product_id)
        .distinct()
        .all()
    )
    marts = set()
    for (s,) in list(rows) + list(rows2):
        n = _normalize(s)
        if n:
            marts.add(n)
    return sorted(marts)


@router.get("/overview")
def overview(identity: dict = Depends(require_viewer)):
    """오늘의 DB 상태 — 카드 + 마트별 분포 + 경고."""
    session = get_session()
    try:
        now = datetime.utcnow()

        total_products = session.execute(select(func.count(Product.id))).scalar() or 0

        # 마트별 상품 분포 (BaselinePrice.source distinct product_id)
        mart_rows = session.execute(
            select(BaselinePrice.source, func.count(distinct(BaselinePrice.product_id)))
            .group_by(BaselinePrice.source)
        ).all()

        mart_distribution: dict[str, int] = {m: 0 for m in KNOWN_MARTS}
        other_total = 0
        for raw_src, cnt in mart_rows:
            n = _normalize(raw_src) or ""
            if n in mart_distribution:
                mart_distribution[n] = (mart_distribution[n] or 0) + int(cnt or 0)
            else:
                other_total += int(cnt or 0)

        # 카테고리 leaf 수 (parent로 참조되지 않는 카테고리)
        all_cats = session.execute(
            select(Category.id, Category.parent_id, Category.depth).where(Category.is_active == True)
        ).all()
        parent_ids = {c.parent_id for c in all_cats if c.parent_id}
        leaf_count = sum(1 for c in all_cats if c.id not in parent_ids)
        total_categories = len(all_cats)

        total_matching = session.execute(select(func.count(MatchingEntry.id))).scalar() or 0

        # 최근 import 시각: CrawlLog.started_at 최대값
        last_import = session.execute(select(func.max(CrawlLog.started_at))).scalar()

        # 경고: 한 마트 0건, 다른 마트 100+건
        nonzero = [v for v in mart_distribution.values() if v > 0]
        zero_marts = [k for k, v in mart_distribution.items() if v == 0]
        warnings: list[dict] = []
        if nonzero and zero_marts:
            max_v = max(nonzero)
            if max_v >= 100:
                for zm in zero_marts:
                    warnings.append({
                        "level": "warning",
                        "code": "MART_EMPTY",
                        "message": f"{zm} 마트의 수집 상품이 0건입니다 (최대 마트 {max_v}건과 큰 격차)",
                    })
        if total_products == 0:
            warnings.append({
                "level": "critical",
                "code": "DB_EMPTY",
                "message": "products 테이블이 비어 있습니다. import 또는 크롤이 필요합니다.",
            })
        if total_matching == 0 and total_products > 0:
            warnings.append({
                "level": "warning",
                "code": "MATCHING_EMPTY",
                "message": "matching_entries가 비어 있어 외부 LLM 미스율이 100% 입니다.",
            })

        return {
            "generatedAt": now.isoformat(),
            "totalProducts": int(total_products),
            "totalCategories": int(total_categories),
            "leafCategories": int(leaf_count),
            "totalMatching": int(total_matching),
            "lastImport": last_import.isoformat() if last_import else None,
            "martDistribution": mart_distribution,
            "otherMarts": other_total,
            "warnings": warnings,
        }
    finally:
        session.close()


@router.get("/products")
def list_products(
    category: Optional[str] = Query(None, description="카테고리 ID (드릴다운). 없으면 전체"),
    include_descendants: bool = Query(True),
    only_single_mart: bool = Query(False, description="단일 마트만 수집된 상품"),
    unit_kind: Optional[str] = Query(None, description="weight/volume/count/pack — attributes.unit_kind"),
    sort_by: str = Query("brand", regex="^(brand|price|updated)$"),
    sort_dir: str = Query("asc", regex="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    identity: dict = Depends(require_viewer),
):
    """카테고리 드릴다운 상품 리스트.

    각 상품에 brand/name_core (MatchingEntry 역참조)와 source_marts (BaselinePrice DISTINCT)를 부착한다.
    """
    session = get_session()
    try:
        # 카테고리 + 하위 카테고리 ID 수집
        category_ids: list[str] = []
        if category:
            category_ids = [category]
            if include_descendants:
                # 단순 prefix 매칭 (Category.id가 "meat.pork.belly" 같은 도트 경로)
                rows = session.execute(
                    select(Category.id).where(
                        or_(Category.id == category, Category.id.like(f"{category}.%"))
                    )
                ).all()
                category_ids = [r[0] for r in rows] or [category]

        q = session.query(Product).filter(Product.is_active == True)
        if category_ids:
            q = q.filter(Product.category_id.in_(category_ids))

        total = q.count()
        prods = q.offset((page - 1) * per_page).limit(per_page).all()
        product_ids = [p.id for p in prods]

        # source_marts 일괄 집계
        marts_by_prod: dict[int, set[str]] = {pid: set() for pid in product_ids}
        if product_ids:
            for src_table in (BaselinePrice, DiscountHistory):
                rows = session.execute(
                    select(src_table.product_id, src_table.source)
                    .where(src_table.product_id.in_(product_ids))
                    .distinct()
                ).all()
                for pid, src in rows:
                    n = _normalize(src)
                    if n:
                        marts_by_prod.setdefault(pid, set()).add(n)

            # baseline 가격 범위
            bp_rows = session.execute(
                select(
                    BaselinePrice.product_id,
                    func.min(BaselinePrice.price),
                    func.max(BaselinePrice.price),
                    func.max(BaselinePrice.recorded_at),
                )
                .where(BaselinePrice.product_id.in_(product_ids))
                .group_by(BaselinePrice.product_id)
            ).all()
            price_range: dict[int, dict] = {
                pid: {"min": mn, "max": mx, "lastRecorded": ts.isoformat() if ts else None}
                for pid, mn, mx, ts in bp_rows
            }

            # MatchingEntry 역참조 (canonical_product_id == str(product.id))
            me_rows = session.execute(
                select(
                    MatchingEntry.canonical_product_id,
                    MatchingEntry.brand,
                    MatchingEntry.name_core,
                    MatchingEntry.pack_qty,
                    MatchingEntry.pack_unit,
                ).where(
                    MatchingEntry.canonical_product_id.in_([str(pid) for pid in product_ids])
                )
            ).all()
            match_meta: dict[int, dict] = {}
            for cpid, brand, name_core, pack_qty, pack_unit in me_rows:
                try:
                    pid_int = int(cpid)
                except (TypeError, ValueError):
                    continue
                match_meta[pid_int] = {
                    "brand": brand,
                    "name_core": name_core,
                    "pack_qty": pack_qty,
                    "pack_unit": pack_unit,
                }
        else:
            price_range = {}
            match_meta = {}

        items = []
        for p in prods:
            marts = sorted(marts_by_prod.get(p.id, set()))
            meta = match_meta.get(p.id, {})
            attrs = p.attributes or {}
            unit_kind_val = attrs.get("unit_kind") if isinstance(attrs, dict) else None
            items.append({
                "id": p.id,
                "name": p.name,
                "brand": meta.get("brand"),
                "name_core": meta.get("name_core"),
                "pack_qty": meta.get("pack_qty"),
                "pack_unit": meta.get("pack_unit") or p.unit,
                "unit_kind": unit_kind_val,
                "category_id": p.category_id,
                "source_marts": marts,
                "mart_count": len(marts),
                "baseline": price_range.get(p.id),
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                "source_type": p.source_type,
            })

        # 후처리 필터 (단일 마트 only)
        if only_single_mart:
            items = [it for it in items if it["mart_count"] <= 1]

        if unit_kind:
            items = [it for it in items if it["unit_kind"] == unit_kind]

        # 정렬
        if sort_by == "brand":
            items.sort(key=lambda it: (it.get("brand") or "", it.get("name") or ""), reverse=(sort_dir == "desc"))
        elif sort_by == "price":
            items.sort(key=lambda it: (it.get("baseline") or {}).get("min") or 0, reverse=(sort_dir == "desc"))
        elif sort_by == "updated":
            items.sort(key=lambda it: it.get("updated_at") or "", reverse=(sort_dir == "desc"))

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "filtered_count": len(items),
            "items": items,
        }
    finally:
        session.close()


@router.get("/integrity")
def integrity_summary(identity: dict = Depends(require_viewer)):
    """RD8 결함 카탈로그 기반 정합성 점검 (운영자용)."""
    session = get_session()
    try:
        total_products = session.execute(select(func.count(Product.id))).scalar() or 0

        # 1. source_marts 비어 있는 product = BaselinePrice + DiscountHistory 둘 다 없음
        with_price_ids = session.execute(
            select(distinct(BaselinePrice.product_id))
        ).all()
        with_price = {r[0] for r in with_price_ids}
        with_disc_ids = session.execute(
            select(distinct(DiscountHistory.product_id))
        ).all()
        with_disc = {r[0] for r in with_disc_ids}
        all_pids = [r[0] for r in session.execute(select(Product.id)).all()]
        no_source = [pid for pid in all_pids if pid not in with_price and pid not in with_disc]

        # 2. baseline_prices 한 product에 1마트만 있는 비율
        bp_mart_counts = session.execute(
            select(BaselinePrice.product_id, func.count(distinct(BaselinePrice.source)))
            .group_by(BaselinePrice.product_id)
        ).all()
        single_mart = [pid for pid, c in bp_mart_counts if c == 1]
        single_mart_ratio = (len(single_mart) / max(len(bp_mart_counts), 1)) * 100 if bp_mart_counts else 0

        # 3. unit_kind 미지정 — attributes.unit_kind가 없는 product
        no_unit_kind = []
        for p in session.execute(select(Product.id, Product.attributes)).all():
            attrs = p.attributes or {}
            if not isinstance(attrs, dict) or not attrs.get("unit_kind"):
                no_unit_kind.append(p.id)

        # 4. 카테고리 미할당 product
        no_cat_rows = session.execute(
            select(Product.id).where(Product.category_id.is_(None))
        ).all()
        no_category = [r[0] for r in no_cat_rows]

        # 5. 중복 의심: MatchingEntry brand+name_core 중복 (multi canonical)
        dup_rows = session.execute(
            select(MatchingEntry.brand, MatchingEntry.name_core, func.count(literal(1)))
            .where(MatchingEntry.brand.isnot(None), MatchingEntry.name_core.isnot(None))
            .group_by(MatchingEntry.brand, MatchingEntry.name_core)
            .having(func.count(literal(1)) > literal(1))
        ).all()
        duplicate_suspects = [
            {"brand": b, "name_core": n, "count": int(c)} for b, n, c in dup_rows
        ]

        return {
            "generatedAt": datetime.utcnow().isoformat(),
            "totalProducts": int(total_products),
            "checks": [
                {
                    "key": "no_source_marts",
                    "label": "수집 마트 미상 (BaselinePrice/DiscountHistory 모두 0건)",
                    "count": len(no_source),
                    "severity": "critical" if no_source else "ok",
                    "sample_product_ids": no_source[:50],
                },
                {
                    "key": "single_mart_baseline",
                    "label": "기준가가 1개 마트에만 존재하는 상품",
                    "count": len(single_mart),
                    "ratio": round(single_mart_ratio, 1),
                    "severity": "warning" if single_mart_ratio >= 50 else "ok",
                    "sample_product_ids": single_mart[:50],
                },
                {
                    "key": "no_unit_kind",
                    "label": "unit_kind 미지정 (weight/volume/count/pack)",
                    "count": len(no_unit_kind),
                    "severity": "warning" if no_unit_kind else "ok",
                    "sample_product_ids": no_unit_kind[:50],
                },
                {
                    "key": "no_category",
                    "label": "카테고리 미할당 상품",
                    "count": len(no_category),
                    "severity": "warning" if no_category else "ok",
                    "sample_product_ids": no_category[:50],
                },
                {
                    "key": "duplicate_suspects",
                    "label": "중복 의심 (brand+name_core 동일)",
                    "count": len(duplicate_suspects),
                    "severity": "warning" if duplicate_suspects else "ok",
                    "samples": duplicate_suspects[:50],
                },
            ],
        }
    finally:
        session.close()


@router.get("/matching-monitor")
def matching_monitor(identity: dict = Depends(require_viewer)):
    """매칭 누적 모니터 — 최근 7일 자동 분류 비율 / 외부 LLM 의존 비율."""
    session = get_session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)

        # source별 매칭 누적 수
        src_rows = session.execute(
            select(MatchingEntry.source, func.count(MatchingEntry.id))
            .group_by(MatchingEntry.source)
        ).all()
        total_by_src = {s: int(c) for s, c in src_rows}
        total = sum(total_by_src.values()) or 1

        # 최근 7일 신규 매칭
        recent_rows = session.execute(
            select(MatchingEntry.source, func.count(MatchingEntry.id))
            .where(MatchingEntry.created_at >= cutoff)
            .group_by(MatchingEntry.source)
        ).all()
        recent_by_src = {s: int(c) for s, c in recent_rows}
        recent_total = sum(recent_by_src.values()) or 1

        # 최근 7일 hit_count 합 (자동 분류 성공)
        recent_hits = session.execute(
            select(func.sum(MatchingEntry.hit_count))
            .where(MatchingEntry.last_used_at >= cutoff)
        ).scalar() or 0

        return {
            "totalEntries": sum(total_by_src.values()),
            "bySource": total_by_src,
            "recent7d": {
                "added": sum(recent_by_src.values()),
                "bySource": recent_by_src,
                "externalLlmRatio": round((recent_by_src.get("external-ai", 0) / recent_total) * 100, 1),
                "humanRatio": round((recent_by_src.get("human", 0) / recent_total) * 100, 1),
                "crawlerAutoRatio": round((recent_by_src.get("crawler-auto", 0) / recent_total) * 100, 1),
                "hitCount": int(recent_hits),
            },
            "externalLlmRatio": round((total_by_src.get("external-ai", 0) / total) * 100, 1),
        }
    finally:
        session.close()
