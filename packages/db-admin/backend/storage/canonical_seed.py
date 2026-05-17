"""
WalletSavior Phase B6 — canonical 시드 API.

역할:
    4사(이마트·홈플러스·롯데마트·코스트코) raw fixture를 입력받아
    (1) CategoryNode, (2) CanonicalProduct, (3) MartSkuAlias,
    (4) PriceObservation, (5) ProductReviewQueue 5개 테이블에 시드한다.

공개 API:
    seed_categories_from_yaml(session)                              -> int
    seed_from_raw_batch(mart_payloads, session, dry_run, observed_at) -> SeedResult
    seed_canonicals_from_fixture_dir(fixture_dir, session, dry_run)  -> SeedResult

설계 원칙:
    - B1~B4 모듈 import만, 재구현 금지.
    - 멱등: 같은 데이터 두 번 시드해도 중복 없음.
    - 에러 누적: 개별 row 실패가 전체 시드를 막지 않음.
    - dry_run=True: session.flush()까지만, commit 안 함.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# ── 경로 보정: shared/ 가 sys.path에 없으면 추가 ─────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_BACKEND_DIR), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import func, select
from sqlalchemy.orm import Session

# ORM imports — storage 패키지 내 상대 import
from .canonical_models import (
    CategoryNode as ORM_CategoryNode,
    CanonicalProduct as ORM_CanonicalProduct,
    MartKindEnum,
    MartSkuAlias as ORM_MartSkuAlias,
    PriceObservation as ORM_PriceObservation,
    ProductReviewQueue as ORM_ProductReviewQueue,
    ReviewReasonEnum,
    UnitPriceBasisEnum,
)

# B4 canonicalization functions
from core.product_canonicalize import (
    CanonicalizationResult,
    canonicalize_emart,
    canonicalize_homeplus,
    canonicalize_lottemart,
    canonicalize_costco,
    parse_costco_cards_from_html,
)

# category_tree.yaml 위치
_CATEGORY_YAML = _SHARED_DIR / "data" / "category_tree.yaml"

# 마트별 canonicalize 함수 디스패치 테이블
_MART_CANONICALIZERS = {
    "emart": canonicalize_emart,
    "homeplus": canonicalize_homeplus,
    "lottemart": canonicalize_lottemart,
    "costco": canonicalize_costco,
}


# ══════════════════════════════════════════════════════
# SeedResult
# ══════════════════════════════════════════════════════

@dataclass
class SeedResult:
    """시드 실행 결과 요약."""
    canonical_inserted: int = 0
    canonical_updated: int = 0       # 같은 canonical_id로 두 번째 이상
    sku_alias_inserted: int = 0
    price_obs_inserted: int = 0
    review_queue_inserted: int = 0
    category_nodes_present: int = 0  # 시드 후 CategoryNode 테이블 총 행 수
    dry_run: bool = False
    errors: list[dict] = field(default_factory=list)  # {raw_payload_hash, mart, reason}

    def summary_line(self) -> str:
        mode = "[DRY-RUN]" if self.dry_run else "[COMMIT]"
        return (
            f"{mode} canonical +{self.canonical_inserted}/~{self.canonical_updated} "
            f"alias +{self.sku_alias_inserted} "
            f"price +{self.price_obs_inserted} "
            f"queue +{self.review_queue_inserted} "
            f"cat={self.category_nodes_present} "
            f"err={len(self.errors)}"
        )


# ══════════════════════════════════════════════════════
# 내부 헬퍼
# ══════════════════════════════════════════════════════

def _payload_hash(raw: dict) -> str:
    return hashlib.sha1(
        json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _upsert_canonical(
    canonical,
    session: Session,
    seed_result: SeedResult,
) -> None:
    """CanonicalProduct upsert — 같은 id면 update, 없으면 insert."""
    now = datetime.now()
    existing = session.get(ORM_CanonicalProduct, canonical.id)
    if existing is None:
        # category_path_internal 은 "household/sanitary/kitchen_towel" 형태.
        # ORM FK(category_path_internal_id)는 leaf node id만 저장.
        cat_id: Optional[str] = None
        if canonical.category_path_internal:
            parts = canonical.category_path_internal.split("/")
            cat_id = parts[-1] if parts else None

        session.add(ORM_CanonicalProduct(
            id=canonical.id,
            brand=canonical.brand,
            name_core=canonical.name_core,
            pack_quantity=canonical.pack_quantity,
            pack_unit=canonical.pack_unit,
            category_path_internal_id=cat_id,
            representative_image_url=canonical.representative_image_url,
            created_at=now,
            updated_at=now,
        ))
        seed_result.canonical_inserted += 1
    else:
        existing.updated_at = now
        if canonical.representative_image_url:
            existing.representative_image_url = canonical.representative_image_url
        seed_result.canonical_updated += 1


def _upsert_sku_alias(
    alias,
    session: Session,
    seed_result: SeedResult,
    observed_at: datetime,
) -> None:
    """MartSkuAlias upsert — UNIQUE(mart, mart_item_id) 충돌 시 last_seen_at 갱신."""
    existing = session.get(ORM_MartSkuAlias, alias.id)
    if existing is None:
        session.add(ORM_MartSkuAlias(
            id=alias.id,
            canonical_id=alias.canonical_id,
            mart=MartKindEnum(alias.mart.value),
            mart_item_id=alias.mart_item_id,
            mart_item_name_raw=alias.mart_item_name_raw,
            source_url=alias.source_url,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        ))
        seed_result.sku_alias_inserted += 1
    else:
        existing.last_seen_at = observed_at


def _insert_price_obs(
    price_obs,
    session: Session,
    seed_result: SeedResult,
) -> None:
    """PriceObservation insert — 같은 (canonical_id, mart, observed_at) → id 동일 → skip."""
    existing = session.get(ORM_PriceObservation, price_obs.id)
    if existing is None:
        session.add(ORM_PriceObservation(
            id=price_obs.id,
            canonical_id=price_obs.canonical_id,
            mart=MartKindEnum(price_obs.mart.value),
            regular_price=price_obs.regular_price,
            sale_price=price_obs.sale_price,
            on_sale=price_obs.on_sale,
            discount_rate=price_obs.discount_rate,
            unit_price_normalized=price_obs.unit_price_normalized,
            unit_price_basis=UnitPriceBasisEnum(price_obs.unit_price_basis.value),
            observed_at=price_obs.observed_at,
            source_url=price_obs.source_url,
            raw_payload_hash=price_obs.raw_payload_hash,
            event_labels=price_obs.event_labels,
        ))
        seed_result.price_obs_inserted += 1


def _insert_review_queue(
    queue_entry,
    session: Session,
    seed_result: SeedResult,
) -> None:
    """ProductReviewQueue insert — 같은 id면 skip (멱등)."""
    existing = session.get(ORM_ProductReviewQueue, queue_entry.id)
    if existing is None:
        session.add(ORM_ProductReviewQueue(
            id=queue_entry.id,
            raw_payload=queue_entry.raw_payload,
            source_mart=MartKindEnum(queue_entry.source_mart.value),
            reason=ReviewReasonEnum(queue_entry.reason.value),
            suggested_canonical_id=queue_entry.suggested_canonical_id,
            created_at=datetime.now(),
            resolved_at=None,
            resolver_user_id=None,
        ))
        seed_result.review_queue_inserted += 1


def _process_result(
    result: CanonicalizationResult,
    session: Session,
    seed_result: SeedResult,
    observed_at: datetime,
) -> None:
    """단일 CanonicalizationResult로부터 ORM 행 생성/갱신."""
    if result.canonical is not None:
        _upsert_canonical(result.canonical, session, seed_result)
        if result.sku_alias is not None:
            _upsert_sku_alias(result.sku_alias, session, seed_result, observed_at)
        if result.price_obs is not None:
            _insert_price_obs(result.price_obs, session, seed_result)
    if result.queue_entry is not None:
        _insert_review_queue(result.queue_entry, session, seed_result)


# ══════════════════════════════════════════════════════
# Fixture 파서 — 각 마트 파일 → list[dict]
# ══════════════════════════════════════════════════════

def _parse_emart_raw(fixture_dir: Path) -> list[dict]:
    """
    이마트 fixture JSON → raw item list.
    경로: props.pageProps.dehydratedState.queries[].state.data.areaList[].dataList[]
    복수 queries × 복수 areaList 평탄화.
    선호 파일: sale_listing_5cards.json (없으면 *.json 전체)
    """
    emart_dir = fixture_dir / "emart"
    if not emart_dir.exists():
        return []
    pref = emart_dir / "sale_listing_5cards.json"
    files = [pref] if pref.exists() else list(emart_dir.glob("*.json"))

    items: list[dict] = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            queries = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("dehydratedState", {})
                    .get("queries", [])
            )
            for q in queries:
                for area in q.get("state", {}).get("data", {}).get("areaList", []):
                    items.extend(area.get("dataList", []))
        except Exception:
            pass  # 구조 불일치 파일 → skip
    return items


def _parse_homeplus_raw(fixture_dir: Path) -> list[dict]:
    """
    홈플러스 fixture JSON → raw item list.
    경로: data.dataList[]
    선호 파일: sale_listing_5items_dc_mixed.json
    """
    homeplus_dir = fixture_dir / "homeplus"
    if not homeplus_dir.exists():
        return []
    pref = homeplus_dir / "sale_listing_5items_dc_mixed.json"
    files = [pref] if pref.exists() else list(homeplus_dir.glob("*.json"))

    items: list[dict] = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            items.extend(data.get("data", {}).get("dataList", []))
        except Exception:
            pass
    return items


def _parse_lottemart_raw(fixture_dir: Path) -> list[dict]:
    """
    롯데마트 fixture HTML → productEntity list.
    window.__INITIAL_STATE__ = {...};</script> 인라인 JSON 추출.
    트릭: re.S로 멀티라인 매칭. .*? lazy로 첫 번째 </script> 에서 종료.
    선호 파일: hydrated_5cards.html
    """
    lottemart_dir = fixture_dir / "lottemart"
    if not lottemart_dir.exists():
        return []
    pref = lottemart_dir / "hydrated_5cards.html"
    files = [pref] if pref.exists() else list(lottemart_dir.glob("*.html"))

    items: list[dict] = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                html = fp.read()
            m = re.search(
                r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});</script>",
                html, re.S
            )
            if m:
                data = json.loads(m.group(1))
                entities = (
                    data.get("data", {})
                        .get("products", {})
                        .get("productEntities", {})
                )
                items.extend(entities.values())
        except Exception:
            pass
    return items


def _parse_costco_raw(fixture_dir: Path) -> list[dict]:
    """
    코스트코 fixture HTML → card list.
    B4 parse_costco_cards_from_html 재사용.
    선호 파일: special_offers_5cards.html
    """
    costco_dir = fixture_dir / "costco"
    if not costco_dir.exists():
        return []
    pref = costco_dir / "special_offers_5cards.html"
    files = [pref] if pref.exists() else list(costco_dir.glob("*.html"))

    cards: list[dict] = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                html = fp.read()
            cards.extend(parse_costco_cards_from_html(html))
        except Exception:
            pass
    return cards


# ══════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════

def seed_categories_from_yaml(session: Session) -> int:
    """
    category_tree.yaml 로드 → CategoryNode 테이블 멱등 시드.

    - YAML 노드는 parent 보다 항상 먼저 등장한다고 가정 (파일 설계 원칙).
    - level: parent 체인 depth 계산.
    - path: "/{L1 name_kr}/{L2 name_kr}/..." 한글 슬래시 경로.
    - name_slug: node id(stable ASCII slug) 재사용.
    - 이미 있는 노드는 skip (멱등).

    반환: 시드 후 테이블의 CategoryNode 총 수.
    """
    with open(_CATEGORY_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    nodes_raw = data.get("nodes", [])
    node_meta: dict[str, dict] = {}  # id -> {name_kr, parent_id, level, path}

    for item in nodes_raw:
        node_id = item["id"]
        parent_id = item.get("parent_id")

        # level 계산
        if parent_id and parent_id in node_meta:
            level = node_meta[parent_id]["level"] + 1
        else:
            level = 1

        # path 계산 (root → node 한글 이름 chain)
        parts = [item["name_kr"]]
        pid = parent_id
        while pid and pid in node_meta:
            parts.append(node_meta[pid]["name_kr"])
            pid = node_meta[pid]["parent_id"]
        path = "/" + "/".join(reversed(parts))

        node_meta[node_id] = {
            "name_kr": item["name_kr"],
            "parent_id": parent_id,
            "level": level,
            "path": path,
        }

        # 멱등 insert — PK 존재 시 skip
        existing = session.get(ORM_CategoryNode, node_id)
        if existing is None:
            session.add(ORM_CategoryNode(
                id=node_id,
                parent_id=parent_id if parent_id else None,
                name_kr=item["name_kr"],
                name_slug=node_id,
                level=level,
                path=path,
                display_order=item.get("display_order", 0),
            ))

    session.flush()

    count = session.execute(
        select(func.count()).select_from(ORM_CategoryNode)
    ).scalar()
    return count or 0


def seed_from_raw_batch(
    mart_payloads: dict[str, list[dict]],
    session: Session,
    dry_run: bool,
    observed_at: datetime,
) -> SeedResult:
    """
    mart_payloads: {"emart": [...], "homeplus": [...], "lottemart": [...], "costco": [...]}

    각 raw item → canonicalize → upsert/insert.
    에러는 SeedResult.errors[]에 누적 (트랜잭션 abort 금지).
    dry_run=True: session.flush() 까지만. commit 금지.
    dry_run=False: session.commit().
    """
    seed_result = SeedResult(dry_run=dry_run)

    for mart_key, items in mart_payloads.items():
        canonicalize_func = _MART_CANONICALIZERS.get(mart_key)
        if canonicalize_func is None:
            seed_result.errors.append({
                "raw_payload_hash": "",
                "mart": mart_key,
                "reason": f"알 수 없는 mart: {mart_key}",
            })
            continue

        for raw_item in items:
            try:
                result = canonicalize_func(raw_item, observed_at)
                _process_result(result, session, seed_result, observed_at)
            except Exception as exc:
                ph = _payload_hash(raw_item) if isinstance(raw_item, dict) else ""
                seed_result.errors.append({
                    "raw_payload_hash": ph,
                    "mart": mart_key,
                    "reason": str(exc),
                })

    # 카테고리 노드 수 집계
    cat_count = session.execute(
        select(func.count()).select_from(ORM_CategoryNode)
    ).scalar()
    seed_result.category_nodes_present = cat_count or 0

    if dry_run:
        session.flush()
    else:
        session.commit()

    return seed_result


def seed_canonicals_from_fixture_dir(
    fixture_dir: Path,
    session: Session,
    dry_run: bool,
    observed_at: Optional[datetime] = None,
) -> SeedResult:
    """
    fixture_dir/{emart,homeplus,lottemart,costco}/ 하위 fixture 파일을 파싱해
    seed_from_raw_batch를 호출한다.

    빈 디렉터리 또는 해당 마트 서브디렉터리 없음 → 해당 마트 skip.
    파일 파싱 실패 → 해당 파일 skip.
    """
    if observed_at is None:
        observed_at = datetime.now()

    mart_payloads: dict[str, list[dict]] = {}

    emart_items = _parse_emart_raw(fixture_dir)
    if emart_items:
        mart_payloads["emart"] = emart_items

    homeplus_items = _parse_homeplus_raw(fixture_dir)
    if homeplus_items:
        mart_payloads["homeplus"] = homeplus_items

    lottemart_items = _parse_lottemart_raw(fixture_dir)
    if lottemart_items:
        mart_payloads["lottemart"] = lottemart_items

    costco_items = _parse_costco_raw(fixture_dir)
    if costco_items:
        mart_payloads["costco"] = costco_items

    return seed_from_raw_batch(mart_payloads, session, dry_run, observed_at)
