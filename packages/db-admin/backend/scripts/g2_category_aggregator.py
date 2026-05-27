"""G2 category aggregation and unified tree proposal generator.

Usage:
    py -3 -m db_admin.backend.scripts.g2_category_aggregator \
        --output devlog/round-R/g2-unified-tree.yaml
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

MARTS = ("emart", "homeplus", "lottemart", "costco")

FOOD_GROUPS: list[tuple[str, str, list[str]]] = [
    ("fruit", "과일", ["과일", "귤", "한라봉", "감귤", "사과", "배", "토마토", "딸기", "블루베리", "체리", "포도", "바나나", "파인애플", "키위", "참다래", "망고", "수박", "멜론", "복숭아", "자두"]),
    ("vegetables", "채소", ["채소", "두부", "나또", "콩나물", "숙주", "고구마", "감자", "양파", "파", "마늘", "생강", "오이", "당근", "호박", "가지", "옥수수", "고추", "파프리카", "피망", "버섯", "샐러드"]),
    ("rice-grains", "쌀/잡곡/견과", ["쌀", "잡곡", "견과", "백미", "현미", "흑미", "찹쌀", "콩", "팥", "보리", "귀리", "혼합곡", "슈퍼곡물"]),
    ("meat-eggs", "정육/계란", ["정육", "계란", "메추리알", "일반란", "소고기", "돼지고기", "닭고기", "양고기", "축산", "햄", "소시지", "가공육"]),
    ("seafood", "수산/건해산", ["수산", "해산", "생선", "오징어", "문어", "낙지", "주꾸미", "새우", "게", "랍스터", "전복", "굴", "조개", "건어물"]),
    ("deli", "델리/즉석조리", ["델리", "즉석", "초밥", "김밥", "치킨", "튀김", "꼬치", "구이", "도시락", "샐러드"]),
    ("bakery", "베이커리/빵", ["베이커리", "빵", "잼", "식빵", "모닝롤", "베이글", "케이크", "쿠키", "마카롱"]),
    ("dairy", "우유/유제품", ["우유", "유제품", "두유", "요거트", "요구르트", "치즈", "버터", "마가린"]),
    ("kimchi-sides", "김치/반찬", ["김치", "반찬", "젓갈", "단무지", "쌈무", "우엉", "나물"]),
    ("noodles-rice", "라면/면/즉석밥", ["라면", "통조림", "즉석밥", "컵밥", "즉석죽", "스프", "건면", "생면", "면요리", "우동", "냉면", "쫄면", "짜장면", "떡"]),
    ("condiments", "양념/오일/소스", ["양념", "오일", "분말", "장류", "소스", "케찹", "마요네즈", "머스타드", "드레싱", "식용유", "참기름", "식초"]),
    ("ready-meals", "간편식/밀키트", ["간편식", "밀키트", "간편면", "국", "탕", "찌개", "전골", "떡볶이", "분식", "피자", "핫도그", "닭가슴살", "어묵", "맛살"]),
    ("snacks", "과자/간식", ["과자", "스낵", "간식", "초콜릿", "사탕", "껌", "젤리", "푸딩", "떡", "한과", "전통과자", "맛밤", "김스낵", "과일칩"]),
    ("icecream", "아이스크림/빙과", ["아이스크림", "빙과", "파인트", "콘", "바", "막대", "튜브"]),
    ("beverages", "생수/음료", ["생수", "음료", "탄산수", "탄산음료", "주스", "과일음료", "야채음료", "어린이음료"]),
    ("coffee-tea", "커피/차", ["커피", "원두", "커피믹스", "프림", "드립백", "캡슐", "더치커피", "차", "액상차", "핫초코", "녹차", "보리차", "옥수수차", "홍차", "밀크티", "아이스티", "허브차", "꽃차", "과일차", "곡물차", "꿀"]),
    ("health-food", "건강식품", ["건강식품", "비타민", "유산균", "영양제", "홍삼", "프로폴리스"]),
    ("imported", "수입식품", ["수입식품", "수입유제품", "수입잼", "수입소스", "수입통조림", "수입음료"]),
]

NON_FOOD_GROUPS: list[tuple[str, str, list[str]]] = [
    ("baby", "분유/기저귀/유아용품", ["분유", "기저귀", "유아", "이유식"]),
    ("household", "생활용품", ["제지", "세제", "생활용품", "화장지", "물티슈", "키친타올", "청소", "욕실", "세탁"]),
    ("beauty", "헤어/바디/뷰티", ["헤어", "바디", "뷰티", "구강", "치약", "칫솔", "면도", "제모", "스킨케어"]),
    ("kitchen", "주방용품", ["주방용품", "주방잡화", "식기", "그릇", "수저", "잔", "컵", "텀블러", "보관", "밀폐"]),
    ("home", "홈인테리어/침구", ["홈인테리어", "침구", "이불", "쿠션", "수납", "커튼", "카페트", "러그", "매트"]),
    ("pet", "반려동물", ["반려동물", "강아지", "고양이", "사료", "간식"]),
    ("fashion", "패션/잡화", ["언더웨어", "홈웨어", "양말", "패션잡화", "가방", "모자", "장갑", "벨트", "액세서리"]),
    ("sports-auto", "스포츠/자동차", ["스포츠", "자동차", "골프"]),
    ("stationery", "문구/사무용품", ["문구", "사무", "노트", "메모", "다이어리", "필기도구", "팬시", "미술"]),
    ("toys", "완구/취미", ["완구", "취미", "블록", "로봇", "인형", "역할놀이", "학습완구"]),
    ("digital", "가전/디지털/게임", ["전자게임", "가전", "디지털", "닌텐도", "플레이스테이션", "생활가전", "주변기기"]),
]

LEAF_HINTS: list[tuple[str, str, list[str]]] = [
    ("citrus", "귤/감귤류", ["귤", "한라봉", "감귤"]),
    ("apple-pear", "사과/배", ["사과", "배"]),
    ("tomato", "토마토", ["토마토"]),
    ("berries", "딸기/베리/체리", ["딸기", "블루베리", "체리"]),
    ("grape", "포도/샤인머스캣", ["포도", "샤인머스캣"]),
    ("kiwi-pineapple", "키위/파인애플", ["키위", "참다래", "파인애플"]),
    ("tofu-bean-sprouts", "두부/콩나물", ["두부", "나또", "콩나물", "숙주"]),
    ("root-vegetables", "감자/고구마/당근", ["감자", "고구마", "당근"]),
    ("aromatics", "양파/파/마늘", ["양파", "파", "마늘", "생강"]),
    ("pepper-paprika", "고추/파프리카", ["고추", "파프리카", "피망"]),
    ("rice", "쌀/백미", ["쌀", "백미", "오대쌀"]),
    ("mixed-grains", "잡곡/혼합곡", ["잡곡", "현미", "흑미", "찹쌀", "혼합곡", "콩", "보리", "귀리"]),
    ("nuts", "견과", ["견과"]),
    ("beef", "소고기", ["소고기", "한우"]),
    ("pork", "돼지고기", ["돼지고기"]),
    ("chicken", "닭고기/닭가슴살", ["닭고기", "닭가슴살", "치킨"]),
    ("eggs", "계란", ["계란", "메추리알", "일반란"]),
    ("milk", "우유", ["우유"]),
    ("soy-milk", "두유", ["두유"]),
    ("yogurt", "요거트/요구르트", ["요거트", "요구르트"]),
    ("cheese-butter", "치즈/버터", ["치즈", "버터", "마가린"]),
    ("water", "생수", ["생수"]),
    ("soda", "탄산수/탄산음료", ["탄산"]),
    ("juice", "주스/과채음료", ["주스", "과일음료", "야채음료"]),
    ("ramen", "라면", ["라면"]),
    ("instant-rice", "즉석밥/컵밥", ["즉석밥", "컵밥"]),
    ("oil", "식용유/참기름", ["식용유", "참기름", "오일"]),
    ("sauce", "소스/장류", ["소스", "장류", "케찹", "마요네즈", "머스타드", "드레싱"]),
    ("meal-kit", "밀키트", ["밀키트"]),
    ("soup-stew", "국/탕/찌개", ["국", "탕", "찌개", "전골"]),
]

@dataclass(frozen=True)
class NativeCategory:
    mart: str
    native_id: str
    path: str
    source: str
    product_count: int = 0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_db_path(root: Path) -> Path:
    return root / "packages" / "db-admin" / "backend" / "walletguardian.db"


def read_db_categories(db_path: Path) -> list[NativeCategory]:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return []
    query = """
        SELECT mart,
               COALESCE(mart_native_category_id, ''),
               COALESCE(mart_native_category_path, ''),
               COUNT(*)
        FROM products
        WHERE mart IS NOT NULL AND COALESCE(mart_native_category_path, '') <> ''
        GROUP BY mart, mart_native_category_id, mart_native_category_path
        ORDER BY mart, mart_native_category_path
    """
    with sqlite3.connect(str(db_path)) as conn:
        try:
            rows = conn.execute(query).fetchall()
        except sqlite3.Error:
            return []
    return [NativeCategory(str(m), str(cid), str(path), "db", int(count)) for m, cid, path, count in rows]


def _split_path(path: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*>\s*", path) if part.strip()]


def _native_value(cat: NativeCategory) -> str:
    return cat.native_id or cat.path


def _add_unique(target: dict[str, list[str]], mart: str, value: str) -> None:
    if not value:
        return
    vals = target.setdefault(mart, [])
    if value not in vals:
        vals.append(value)


def _extract_lottemart_fixture(root: Path) -> list[NativeCategory]:
    path = root / "packages" / "crawler-admin" / "backend" / "tests" / "fixtures" / "live_probe" / "lottemart_zetta_browse_root.html"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    match = re.search(r"window\.__INITIAL_STATE__=(\{.*?\})</script>", text)
    if not match:
        return []
    state = json.loads(match.group(1))
    data = state.get("data", {}).get("categories", {})
    categories = data.get("categories") or {}
    root_ids = data.get("root") or []
    records: list[NativeCategory] = []
    for root_id in root_ids:
        cat = categories.get(root_id) or {}
        name = cat.get("name")
        native_id = str(cat.get("retailerId") or cat.get("id") or root_id)
        if name:
            records.append(NativeCategory("lottemart", native_id, str(name), "fixture:lottemart_zetta_browse_root.html"))
        for child_id in cat.get("children") or []:
            child = categories.get(child_id) or {}
            child_name = child.get("name")
            child_native = str(child.get("retailerId") or child.get("id") or child_id)
            if name and child_name:
                records.append(NativeCategory("lottemart", child_native, f"{name} > {child_name}", "fixture:lottemart_zetta_browse_root.html"))
    return records


def _extract_homeplus_fixture(root: Path) -> list[NativeCategory]:
    path = root / "packages" / "crawler-admin" / "backend" / "tests" / "fixtures" / "homeplus_category_tree_g1.json"
    if not path.exists():
        return []
    records: list[NativeCategory] = []
    for row in json.loads(path.read_text(encoding="utf-8")):
        cid = str(row.get("mart_native_category_id") or "")
        store_type = str(row.get("storeType") or "HYPER")
        if cid:
            records.append(NativeCategory("homeplus", cid, f"{store_type} categoryId={cid}", "fixture:homeplus_category_tree_g1.json"))
    return records


def _extract_costco_fixtures(root: Path) -> list[NativeCategory]:
    records: list[NativeCategory] = []
    fixture = root / "packages" / "crawler-admin" / "backend" / "tests" / "fixtures" / "costco" / "cocodalin_productlist_cat10.json"
    if fixture.exists():
        names = sorted({str(row.get("category_name")) for row in json.loads(fixture.read_text(encoding="utf-8")) if row.get("category_name")})
        for idx, name in enumerate(names, 1):
            records.append(NativeCategory("costco", f"cocodalin_{idx}", name, "fixture:cocodalin_productlist_cat10.json"))
    occ = root / "packages" / "crawler-admin" / "backend" / "tests" / "fixtures" / "costco" / "occ_products_3items.json"
    if occ.exists():
        for product in (json.loads(occ.read_text(encoding="utf-8")).get("products") or []):
            url = str(product.get("url") or "")
            parts = [p for p in url.split("/") if p and p != "p"]
            if len(parts) >= 3:
                records.append(NativeCategory("costco", str(product.get("code") or ""), " > ".join(parts[:-2]), "fixture:occ_products_3items.json"))
    return records


def _extract_emart_fixture(root: Path) -> list[NativeCategory]:
    path = root / "packages" / "crawler-admin" / "backend" / "tests" / "fixtures" / "emart_category_sample.html"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r"dispCtgId=(\d+)", text)))
    return [NativeCategory("emart", cid, "fixture category page", "fixture:emart_category_sample.html") for cid in ids]


def read_fixture_categories(root: Path) -> list[NativeCategory]:
    records: list[NativeCategory] = []
    records.extend(_extract_lottemart_fixture(root))
    records.extend(_extract_homeplus_fixture(root))
    records.extend(_extract_costco_fixtures(root))
    records.extend(_extract_emart_fixture(root))
    return records


def read_recon_docs(root: Path) -> dict[str, list[str]]:
    docs: dict[str, list[str]] = {}
    for mart in MARTS:
        path = root / "devlog" / "round-R" / f"G0-{mart}.md"
        if not path.exists():
            docs[mart] = []
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        matches = [line.strip("- ") for line in lines if "최상위" in line or "하위" in line or "식품" in line]
        docs[mart] = matches
    return docs


def choose_authoritative(db_records: list[NativeCategory], fixture_records: list[NativeCategory]) -> tuple[str, str]:
    fixture_counts = {mart: len({(r.native_id, r.path) for r in fixture_records if r.mart == mart}) for mart in MARTS}
    if fixture_counts.get("emart", 0) < max(fixture_counts.values() or [0]):
        mart = max(fixture_counts, key=lambda m: (fixture_counts[m], m == "emart"))
        return mart, f"emart recon decision was sparse ({fixture_counts.get('emart', 0)} fixture categories); {mart} has richest harvested tree ({fixture_counts[mart]} fixture categories)."
    return "emart", "Matches G0-schema and handover decision; no richer fixture tree superseded it."


def _match_group(text: str, groups: Iterable[tuple[str, str, list[str]]]) -> tuple[str, str] | None:
    for slug, name, keywords in groups:
        if any(keyword and keyword in text for keyword in keywords):
            return slug, name
    return None


def map_category(cat: NativeCategory) -> tuple[list[str], str | None]:
    text = cat.path.replace("ㆍ", " ").replace("/", " ")
    if cat.mart == "homeplus" and cat.source.startswith("fixture"):
        return [], "homeplus fixture has categoryId only; needs name harvest before mapping"
    if cat.mart == "emart" and "과일/채소" in cat.path:
        return ["food.fruit", "food.vegetables"], "emart path combines fruit and vegetables"
    group = _match_group(text, FOOD_GROUPS)
    if group:
        group_slug, _ = group
        leaf = _match_group(text, LEAF_HINTS) if len(_split_path(cat.path)) > 1 else None
        if leaf:
            return [f"food.{group_slug}.{leaf[0]}"], None
        return [f"food.{group_slug}"], None
    group = _match_group(text, NON_FOOD_GROUPS)
    if group:
        return [group[0]], None
    if text in {"식품", "FoodandBeverage", "FreshFood"} or "Food" in text:
        return ["food"], None
    return [], "no keyword overlap with unified v1 taxonomy"


def _empty_sources() -> dict[str, list[str]]:
    return {mart: [] for mart in MARTS}


def _node(node_id: str, name: str, parent_id: str | None, children: list[str], sources: dict[str, dict[str, list[str]]]) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": name,
        "parent_id": parent_id,
        "children": children,
        "source_natives": {mart: sorted(sources.get(node_id, {}).get(mart, [])) for mart in MARTS},
    }


def _ensure_ancestors(node_id: str) -> list[str]:
    parts = node_id.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def build_tree(db_records: list[NativeCategory], fixture_records: list[NativeCategory], recon_docs: dict[str, list[str]]) -> dict[str, Any]:
    all_records = db_records + fixture_records
    authoritative, reason = choose_authoritative(db_records, fixture_records)
    sources: dict[str, dict[str, list[str]]] = defaultdict(_empty_sources)
    review_queue: list[dict[str, Any]] = []

    for cat in all_records:
        mapped_ids, reason_text = map_category(cat)
        native = _native_value(cat)
        for mapped_id in mapped_ids:
            for ancestor in _ensure_ancestors(mapped_id):
                _add_unique(sources[ancestor], cat.mart, native)
        if reason_text:
            review_queue.append({
                "mart": cat.mart,
                "native_id": cat.native_id,
                "path": cat.path,
                "source": cat.source,
                "reason": reason_text,
                "suggested_nodes": mapped_ids,
                "status": "needs_review",
            })

    nodes: list[dict[str, Any]] = []
    food_children = [f"food.{slug}" for slug, _, _ in FOOD_GROUPS]
    nodes.append(_node("food", "식품", None, food_children, sources))
    for slug, name, _keywords in FOOD_GROUPS:
        leaf_ids = []
        for leaf_slug, leaf_name, leaf_keywords in LEAF_HINTS:
            # Keep only leaves whose hints map back to this group.
            group = _match_group(" ".join(leaf_keywords), [(slug, name, _keywords)])
            if group:
                leaf_ids.append(f"food.{slug}.{leaf_slug}")
        nodes.append(_node(f"food.{slug}", name, "food", leaf_ids, sources))
        for leaf_slug, leaf_name, leaf_keywords in LEAF_HINTS:
            if _match_group(" ".join(leaf_keywords), [(slug, name, _keywords)]):
                nodes.append(_node(f"food.{slug}.{leaf_slug}", leaf_name, f"food.{slug}", [], sources))

    for slug, name, _keywords in NON_FOOD_GROUPS:
        nodes.append(_node(slug, name, None, [], sources))

    counts = {
        mart: {
            "db_distinct": len({(r.native_id, r.path) for r in db_records if r.mart == mart}),
            "fixture_distinct": len({(r.native_id, r.path) for r in fixture_records if r.mart == mart}),
            "source_native_values": len({v for node_sources in sources.values() for v in node_sources.get(mart, [])}),
        }
        for mart in MARTS
    }
    return {
        "schema": "unified_category_tree.v1",
        "authoritative_mart": authoritative,
        "authoritative_reason": reason,
        "source_inventory": {
            "counts": counts,
            "recon_top_categories": recon_docs,
        },
        "nodes": nodes,
        "review_queue": sorted(review_queue, key=lambda r: (r["mart"], r["path"], r["native_id"], r["source"])),
    }


def write_yaml(tree: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(tree, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")


def write_report(tree: dict[str, Any], output: Path, db_records: list[NativeCategory], fixture_records: list[NativeCategory]) -> Path:
    report_path = output.with_name("g2-aggregate-report.md")
    counts = tree["source_inventory"]["counts"]
    review = tree["review_queue"]
    excerpt_nodes = []
    for node_id in ("food", "food.dairy", "food.dairy.milk"):
        original = next(node for node in tree["nodes"] if node["id"] == node_id)
        excerpt_node = dict(original)
        excerpt_node["source_natives"] = {
            mart: values[:5] + (["..."] if len(values) > 5 else [])
            for mart, values in original["source_natives"].items()
        }
        excerpt_nodes.append(excerpt_node)
    excerpt = yaml.safe_dump({"schema": tree["schema"], "authoritative_mart": tree["authoritative_mart"], "nodes": excerpt_nodes}, allow_unicode=True, sort_keys=False, width=1000)
    lines = [
        "# G2 Aggregate Report",
        "",
        "## Authoritative mart",
        f"- Chosen: `{tree['authoritative_mart']}`",
        f"- Reason: {tree['authoritative_reason']}",
        "",
        "## Counts per mart",
        "| mart | DB distinct native paths | fixture categories | mapped source_native values |",
        "| --- | ---: | ---: | ---: |",
    ]
    for mart in MARTS:
        c = counts[mart]
        lines.append(f"| {mart} | {c['db_distinct']} | {c['fixture_distinct']} | {c['source_native_values']} |")
    lines.extend([
        "",
        "## Review queue stats",
        f"- total: {len(review)}",
    ])
    by_mart = defaultdict(int)
    for item in review:
        by_mart[item["mart"]] += 1
    for mart in MARTS:
        lines.append(f"- {mart}: {by_mart[mart]}")
    lines.extend([
        "",
        "## Sample tree YAML excerpt",
        "```yaml",
        excerpt.rstrip(),
        "```",
        "",
        "## Reproduction one-liner",
        "`py -3 -m db_admin.backend.scripts.g2_category_aggregator --output devlog/round-R/g2-unified-tree.yaml`",
        "",
        "## Inputs inventoried",
        f"- DB categories: {len(db_records)} distinct rows from `products`.",
        f"- Fixture categories: {len(fixture_records)} harvested rows from crawler fixtures.",
    ])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def generate(output: Path, db_path: Path | None = None, *, write_report_file: bool = True) -> dict[str, Any]:
    root = repo_root()
    db_records = read_db_categories(db_path or default_db_path(root))
    fixture_records = read_fixture_categories(root)
    recon_docs = read_recon_docs(root)
    tree = build_tree(db_records, fixture_records, recon_docs)
    write_yaml(tree, output)
    if write_report_file:
        write_report(tree, output, db_records, fixture_records)
    return tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate mart-native categories and propose unified tree v1.")
    parser.add_argument("--output", required=True, type=Path, help="YAML output path")
    parser.add_argument("--db-path", type=Path, default=None, help="SQLite DB path override")
    parser.add_argument("--no-report", action="store_true", help="Do not write g2-aggregate-report.md next to output")
    args = parser.parse_args(argv)
    generate(args.output, args.db_path, write_report_file=not args.no_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
