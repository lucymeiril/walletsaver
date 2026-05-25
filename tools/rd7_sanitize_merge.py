"""RD7: 4 마트 sub-agent 결과 sanitize + merge.

각 sub-agent가 만든 category_id 중 일부가 categories.yaml에 존재하지 않을 수 있음.
- 존재 안 하는 id는 점(.)으로 자르며 parent를 찾아 fallback.
- 모든 prefix가 없으면 'etc' 또는 root 카테고리.
- 4개 폴더의 matching_updates / products / categories_keywords_updates를 단일 export 폴더로 머지.
"""
from __future__ import annotations
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIRS = [
    ROOT / "artifacts/exports/raw-batch/full-emart",
    ROOT / "artifacts/exports/raw-batch/full-homeplus",
    ROOT / "artifacts/exports/raw-batch/full-lottemart",
    ROOT / "artifacts/exports/raw-batch/full-costco",
]
DST = ROOT / "artifacts/exports/raw-batch/full-merged"


def load_category_ids() -> set[str]:
    txt = (SRC_DIRS[0] / "context/categories.yaml").read_text(encoding="utf-8")
    return set(re.findall(r"^- id: ([\w\.]+)\s*$", txt, re.M))


def fallback(cid: str, whitelist: set[str]) -> tuple[str, bool]:
    if cid in whitelist:
        return cid, False
    parts = cid.split(".")
    while len(parts) > 1:
        parts.pop()
        cand = ".".join(parts)
        if cand in whitelist:
            return cand, True
    return "etc", True


def main() -> int:
    ids = load_category_ids()
    print(f"whitelist: {len(ids)} category ids")
    DST.mkdir(parents=True, exist_ok=True)
    (DST / "context").mkdir(exist_ok=True)
    shutil.copy2(SRC_DIRS[0] / "context/categories.yaml", DST / "context/categories.yaml")
    shutil.copy2(SRC_DIRS[0] / "context/keywords.yaml", DST / "context/keywords.yaml")
    shutil.copy2(SRC_DIRS[0] / "context/matching_entries.jsonl", DST / "context/matching_entries.jsonl")
    shutil.copy2(SRC_DIRS[0] / "manifest.json", DST / "manifest.json")

    raw_lines: list[str] = []
    match_keys: dict[str, dict] = {}
    product_lines: list[dict] = []
    fallbacks = 0
    total_cat = 0

    for d in SRC_DIRS:
        for ln in (d / "raw_products.jsonl").read_text(encoding="utf-8").splitlines():
            if ln.strip():
                raw_lines.append(ln)
        # matching
        mpath = d / "matching_updates.jsonl"
        if mpath.exists():
            for ln in mpath.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                rec = json.loads(ln)
                cid = rec.get("category_id", "etc")
                total_cat += 1
                new_cid, changed = fallback(cid, ids)
                if changed:
                    fallbacks += 1
                rec["category_id"] = new_cid
                mk = rec.get("match_key")
                if mk and mk not in match_keys:
                    match_keys[mk] = rec
        # products
        ppath = d / "products.jsonl"
        if ppath.exists():
            for ln in ppath.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                rec = json.loads(ln)
                cid = rec.get("category_id")
                if cid:
                    total_cat += 1
                    new_cid, changed = fallback(cid, ids)
                    if changed:
                        fallbacks += 1
                    rec["category_id"] = new_cid
                product_lines.append(rec)

    (DST / "raw_products.jsonl").write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    (DST / "matching_updates.jsonl").write_text(
        "\n".join(json.dumps(v, ensure_ascii=False) for v in match_keys.values()) + "\n",
        encoding="utf-8",
    )
    (DST / "products.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in product_lines) + "\n",
        encoding="utf-8",
    )
    # 빈 categories_keywords_updates.yaml (sub-agent 다 빈 리스트)
    (DST / "categories_keywords_updates.yaml").write_text(
        "categories: []\nkeywords: []\n", encoding="utf-8"
    )

    print(f"raw: {len(raw_lines)}")
    print(f"matching_updates: {len(match_keys)}")
    print(f"products: {len(product_lines)}")
    print(f"category_id fallback: {fallbacks}/{total_cat}")
    print(f"output: {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
