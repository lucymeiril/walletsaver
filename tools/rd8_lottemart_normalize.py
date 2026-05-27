"""rd8_lottemart_normalize.py — lottemart matching_updates_final.jsonl의 pack_qty/pack_unit/match_key 재생성.

이름 끝의 (1.8KG) (300G) (450ML) (EA) (개) (1개입) 등을 regex로 파싱.
match_key는 brand|name_core|pack_qty|pack_unit 형식으로 재조립 (L3 import 요구).
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "artifacts/rd8/l2_classified/lottemart/matching_updates_final.jsonl"

# 단위 매핑: 표기 → (정규화된 단위, kind)
UNIT_MAP = {
    "g": ("g", "weight"),
    "kg": ("g", "weight"),  # → g 환산
    "mg": ("g", "weight"),
    "ml": ("ml", "volume"),
    "l": ("ml", "volume"),  # → ml 환산
    "cc": ("ml", "volume"),
    "ea": ("ea", "count"),
    "개": ("ea", "count"),
    "개입": ("ea", "count"),
    "입": ("ea", "count"),
    "포": ("ea", "count"),
    "팩": ("ea", "count"),
    "장": ("ea", "count"),
    "매": ("ea", "count"),
    "병": ("ea", "count"),
    "캔": ("ea", "count"),
    "봉": ("ea", "count"),
    "롤": ("ea", "count"),
    "구": ("ea", "count"),
    "통": ("ea", "count"),
    "마리": ("ea", "count"),
    "인": ("ea", "count"),
    "set": ("set", "pack"),
}

# 패턴: 숫자(소수허용) + 단위
PAT_QTY_UNIT = re.compile(
    r"\(([\d.,]+)\s*([A-Za-z가-힣]+)\)|"
    r"([\d.,]+)\s*(KG|G|MG|ML|L|CC|EA|개|입|포|팩|장|매|병|캔|봉|롤|마리|인)\b",
    re.IGNORECASE,
)

# EA-only 패턴
PAT_EA_ONLY = re.compile(r"\((EA|개|마리|통|인|입|개입|팩|봉|병|캔)\)", re.IGNORECASE)


def parse_qty_unit(name: str) -> tuple[float | None, str | None, str | None]:
    """이름에서 (qty, unit_normalized, unit_kind) 추출. 못 찾으면 (None,None,None)."""
    if not name:
        return None, None, None
    # 1. (숫자단위) 패턴 우선 (가장 우측의 것을 선택)
    matches = list(PAT_QTY_UNIT.finditer(name))
    if matches:
        m = matches[-1]
        if m.group(1):
            num_str, unit_str = m.group(1), m.group(2)
        else:
            num_str, unit_str = m.group(3), m.group(4)
        try:
            qty = float(num_str.replace(",", ""))
        except ValueError:
            return None, None, None
        u = unit_str.lower().strip()
        if u in UNIT_MAP:
            norm_unit, kind = UNIT_MAP[u]
            # kg→g, L→ml 환산
            if u == "kg":
                qty *= 1000
            elif u == "l":
                qty *= 1000
            elif u == "mg":
                qty /= 1000
                norm_unit = "g"
            return qty, norm_unit, kind
        return qty, u, "pack"
    # 2. (EA) 같은 단위만 있는 패턴 → qty=1
    m = PAT_EA_ONLY.search(name)
    if m:
        u = m.group(1).lower()
        norm_unit, kind = UNIT_MAP.get(u, ("ea", "count"))
        return 1.0, norm_unit, kind
    return None, None, None


def main():
    rows = [json.loads(l) for l in P.read_text(encoding="utf-8").splitlines() if l.strip()]
    fixed = 0
    unparsed = 0
    for r in rows:
        name = r.get("name_core") or r.get("name") or ""
        qty, unit, kind = parse_qty_unit(name)
        if qty is None:
            qty, unit, kind = 1.0, "ea", "count"
            unparsed += 1
        r["pack_qty"] = qty
        r["pack_unit"] = unit
        r["pack_unit_kind"] = kind
        # match_key 재조립: brand|name_core|pack_qty|pack_unit
        brand = r.get("brand") or "롯데마트"
        nc = r.get("name_core") or name
        r["match_key"] = f"{brand}|{nc}|{qty}|{unit}"
        fixed += 1
    P.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"fixed={fixed} unparsed(default 1.0 ea)={unparsed}")
    print(f"sample: {json.dumps(rows[0], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
