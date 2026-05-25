"""rd8_seed_matching.py — RD8 C4-D 매칭 시드 적재 스크립트.

§D 시뮬레이션 표(categories_final_opus.md) 27건 → matching_entries UPSERT.

사용법:
    py -3 tools/rd8_seed_matching.py
        → dry-run

    py -3 tools/rd8_seed_matching.py --commit
        → DB 실제 반영

match_key 형식: brand|name_core|pack_qty|pack_unit
  예: "CJ|햇반|210.000000|g"

canonicalize 규칙:
  - L 단위(리터) → ml 변환 (×1000)
  - KG 단위(킬로그램) → g 변환 (×1000)
  - 대소문자 정규화 (EA, G → 원래 그대로)
  - pack_qty: 6자리 소수점 고정 (%.6f)
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ── sys.path 설정 ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "packages" / "db-admin" / "backend"
_SHARED = _ROOT / "packages" / "shared"
for p in (_BACKEND, _SHARED):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from storage.models import MatchingEntry

# ── DB URL ────────────────────────────────────────────────────────────────────
_DB_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{_BACKEND / 'walletguardian.db'}",
)

_SOURCE = "rd8_c3_seed"
_CONFIDENCE = 0.95


# ════════════════════════════════════════════════════════════════════════════════
# canonicalize 함수
# ════════════════════════════════════════════════════════════════════════════════

def canonicalize_unit(qty: float, unit: str) -> tuple[float, str]:
    """단위를 정규화한다. L→ml, KG→g."""
    u = unit.strip().lower()
    if u in ("l", "리터"):
        return qty * 1000, "ml"
    if u in ("kg", "킬로그램"):
        return qty * 1000, "g"
    return qty, unit.strip()


def build_match_key(brand: str, name_core: str, pack_qty: float, pack_unit: str) -> str:
    """match_key 형식: brand|name_core|pack_qty|pack_unit"""
    qty, unit = canonicalize_unit(pack_qty, pack_unit)
    return f"{brand}|{name_core}|{qty:.6f}|{unit}"


# ════════════════════════════════════════════════════════════════════════════════
# C3 §D 시뮬레이션 시드 데이터 (27건)
# categories_final_opus.md §D에서 추출
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class SeedRow:
    brand: str
    name_core: str
    pack_qty: float
    pack_unit: str
    category_id: str
    raw_label: str  # 원본 표기 (디버깅용)


_SEED_ROWS: list[SeedRow] = [
    SeedRow("CJ", "다시다 쇠고기", 300.0, "g",
            "food.condiment.stock_dasida",
            "CJ 다시다 쇠고기 / 300g"),
    SeedRow("CJ", "햇반", 210.0, "g",
            "food.meal.instant_rice",
            "CJ 햇반 / 210g"),
    SeedRow("롯데", "초코파이", 12.0, "개입",
            "food.snack.pie_cake",
            "[1+1] 롯데 초코파이 12개입"),
    SeedRow("브랜드없음", "애호박", 1.0, "개",
            "food.fresh.vegetable.fruit_vegetable",
            "[농할할인가] 애호박 1개"),
    SeedRow("농심", "신라면", 120.0, "g",
            "food.noodle.ramen_bag",
            "[행사] 농심 신라면 120g"),
    SeedRow("농심", "오징어 땅콩", 85.0, "g",
            "food.snack.peanut_bean_snack",
            "[행사] 농심 오징어 땅콩 85g"),
    SeedRow("브랜드없음", "돼지 삼겹살", 600.0, "g",
            "food.fresh.meat.pork_belly_neck",
            "[행사] 브랜드없음 돼지 삼겹살 600g 냉장"),
    SeedRow("브랜드없음", "행복생생란", 30.0, "입",
            "food.fresh.egg",
            "[행사] 브랜드없음 행복생생란 30입"),
    SeedRow("샘표", "맛간장 금S", 500.0, "ml",
            "food.condiment.soy_sauce",
            "[행사] 샘표 맛간장 금S / 500ml"),
    SeedRow("크라운", "쿠크다스", 75.0, "g",
            "food.snack.biscuit_cookie",
            "[행사] 크라운 쿠크다스 / 75g"),
    SeedRow("브랜드없음", "돼지 삼겹살 구이용", 600.0, "g",
            "food.fresh.meat.pork_belly_neck",
            "국내산 돼지 삼겹살 구이용 냉장 600g"),
    SeedRow("브랜드없음", "꼬깔콘 콘스프맛", 144.0, "g",
            "food.snack.chip",
            "꼬깔콘 콘스프맛 144g"),
    SeedRow("동서식품", "맥심 모카골드", 11.7, "g",
            "beverage.coffee.instant_stick",
            "동서식품 맥심 모카골드 / 11.7g x 100T"),
    SeedRow("동원", "라이트참치", 100.0, "g",
            "food.canned.tuna",
            "동원 라이트참치 100g"),
    SeedRow("롯데칠성", "칠성사이다", 1.5, "L",
            "beverage.soft_drink.cider_lemonlime",
            "롯데칠성 칠성사이다 / 1.5L"),
    SeedRow("브랜드없음", "맛있는두유GT", 200.0, "ml",
            "food.dairy.milk.plant_based",
            "맛있는두유GT 200ml"),
    SeedRow("매일", "바리스타룰스 라떼", 250.0, "ml",
            "food.dairy.coffee_milk",
            "매일 바리스타룰스 라떼 250ml"),
    SeedRow("제스프리", "골드키위", 1.0, "EA",
            "food.fresh.fruit.tropical",
            "브랜드없음 골드키위 EA / 제스프리 골드키위 (EA)"),
    SeedRow("비비고", "김치만두", 350.0, "g",
            "food.meal.frozen_dumpling",
            "비비고 김치만두 350g"),
    SeedRow("서울우유", "1A", 1.0, "L",
            "food.dairy.milk.white",
            "서울우유 1A 1L"),
    SeedRow("양반", "오징어채볶음", 80.0, "g",
            "food.fresh.seafood.fish_dried_salted",
            "양반 오징어채볶음 80g"),
    SeedRow("브랜드없음", "오감자", 80.0, "g",
            "food.snack.chip",
            "오감자 80g"),
    SeedRow("오뚜기", "진라면 매운맛", 120.0, "g",
            "food.noodle.ramen_bag",
            "오뚜기 진라면 매운맛 120g"),
    SeedRow("청정원", "고추장", 500.0, "g",
            "food.condiment.gochujang_doenjang",
            "청정원 (순창 찰)고추장 500g"),
    SeedRow("코카콜라", "코카콜라", 1.5, "L",
            "beverage.soft_drink.cola",
            "코카콜라 / 1.5L"),
    SeedRow("해태", "맛동산", 90.0, "g",
            "food.snack.korean_traditional",
            "해태 맛동산 90g"),
    SeedRow("브랜드없음", "행복생생란 특란", 1800.0, "g",
            "food.fresh.egg",
            "행복생생란 (특란, 30입) 1.8KG"),
]

# §D 자기검열: "농심 오징어 땅콩"은 원문 표에서 cephalopod으로 매핑됐으나
# 운영 매핑에서는 peanut_bean_snack이 올바름. 이 시드에서는 수정값 적용.
# (원문 표의 매핑 오류를 C4에서 수정)


# ════════════════════════════════════════════════════════════════════════════════
# UPSERT 로직
# ════════════════════════════════════════════════════════════════════════════════

def seed_matching_entries(session: Session, commit: bool) -> dict[str, int]:
    """_SEED_ROWS를 MatchingEntry로 UPSERT.

    ON CONFLICT (match_key) → UPDATE category_id, confidence, updated_at
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stats = {"created": 0, "updated": 0, "unchanged": 0}

    for row in _SEED_ROWS:
        match_key = build_match_key(row.brand, row.name_core, row.pack_qty, row.pack_unit)
        existing = session.query(MatchingEntry).filter(
            MatchingEntry.match_key == match_key
        ).first()

        if existing is None:
            entry = MatchingEntry(
                match_key=match_key,
                brand=row.brand,
                name_core=row.name_core,
                pack_qty=row.pack_qty,
                pack_unit=row.pack_unit,
                category_id=row.category_id,
                confidence=_CONFIDENCE,
                source=_SOURCE,
                created_at=now,
                updated_at=now,
                hit_count=0,
                notes=f"rd8_c3_seed: {row.raw_label}",
            )
            session.add(entry)
            stats["created"] += 1
        else:
            changed = (
                existing.category_id != row.category_id
                or abs((existing.confidence or 0) - _CONFIDENCE) > 1e-9
                or existing.source != _SOURCE
            )
            if changed:
                existing.category_id = row.category_id
                existing.confidence = _CONFIDENCE
                existing.source = _SOURCE
                existing.updated_at = now
                existing.notes = f"rd8_c3_seed (updated): {row.raw_label}"
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1

    if commit:
        session.commit()
    else:
        session.flush()

    return stats


# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RD8 C4-D 매칭 시드 UPSERT (§D 27건)"
    )
    parser.add_argument(
        "--commit", action="store_true",
        help="지정하지 않으면 dry-run (롤백)",
    )
    args = parser.parse_args()

    print(f"[INFO] DB URL : {_DB_URL}")
    print(f"[INFO] 시드   : {len(_SEED_ROWS)}건")
    print(f"[INFO] 모드   : {'--commit (실제 반영)' if args.commit else 'dry-run (롤백)'}")
    print()

    engine = create_engine(
        _DB_URL,
        connect_args={"check_same_thread": False} if "sqlite" in _DB_URL else {},
    )
    if "sqlite" in _DB_URL:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA foreign_keys=ON"))

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        stats = seed_matching_entries(session, commit=args.commit)
        if not args.commit:
            session.rollback()

        print("╔══════════════════════════════╗")
        print(f"║ {'dry-run 결과' if not args.commit else '매칭 시드 결과':^28} ║")
        print("╠══════════════════════════════╣")
        print(f"║  created   : {stats['created']:>14}  ║")
        print(f"║  updated   : {stats['updated']:>14}  ║")
        print(f"║  unchanged : {stats['unchanged']:>14}  ║")
        print(f"║  합계      : {sum(stats.values()):>14}  ║")
        print("╚══════════════════════════════╝")

        if args.commit:
            total_rd8 = session.query(MatchingEntry).filter(
                MatchingEntry.source == _SOURCE
            ).count()
            print()
            print(f"[검증] matching_entries[source=rd8_c3_seed] = {total_rd8}건")

    except Exception as e:
        session.rollback()
        print(f"[ERROR] {e}")
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
