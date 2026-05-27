"""
RD8 L2 산출물 결정론적 후처리.

L2 haiku 산출의 명백한 결함을 LLM 없이 채워 넣는다:
- pack_unit_kind None → pack_unit에서 deterministic 분류
- brand None/빈값 → mart_code 한국어명 폴백
- non-leaf category_id → 부모 카테고리로의 매핑 보고만 (재분류는 별도 LLM 호출)

leaf 매핑은 LLM 재분류가 필요하므로 여기서는 진단만.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import yaml
import collections

ROOT = Path(__file__).resolve().parent.parent

MART_KO = {
    'emart': '이마트',
    'homeplus': '홈플러스',
    'lottemart': '롯데마트',
    'costco': '코스트코',
}

WEIGHT_UNITS = {'g','kg','mg','t'}
VOLUME_UNITS = {'ml','l','L','mL'}
COUNT_UNITS = {'개','EA','매','구','입','정','알','조','장','캡슐','정제','캡','tab','tablet'}
PACK_UNITS = {'봉','개입','단','망','팩','캔','병','포','세트','구성','박스','박','꾸러미','곽','입','마리','수'}

def classify_unit_kind(unit: str | None) -> str | None:
    if not unit: return None
    u = str(unit).strip()
    if not u: return None
    if u in WEIGHT_UNITS or u.lower() in {x.lower() for x in WEIGHT_UNITS}:
        return 'weight'
    if u in VOLUME_UNITS or u.lower() in {x.lower() for x in VOLUME_UNITS}:
        return 'volume'
    if u in COUNT_UNITS: return 'count'
    if u in PACK_UNITS: return 'pack'
    # heuristic fallback
    if u.endswith('g') or u.endswith('kg'): return 'weight'
    if u.endswith('ml') or u.endswith('l') or u.endswith('L'): return 'volume'
    return 'pack'  # 알 수 없는 단위는 pack로 보수적 처리

def load_cat_tree():
    data = yaml.safe_load((ROOT/'packages/shared/data/categories_rd8.yaml').read_text(encoding='utf-8'))
    cat_list = data['categories'] if isinstance(data, dict) and 'categories' in data else (data if isinstance(data, list) else list(data.values()))
    ids = set(); parents = set()
    by_id = {}
    for c in cat_list:
        cid = c.get('id')
        if cid:
            ids.add(cid); by_id[cid] = c
        p = c.get('parent')
        if p: parents.add(p)
    leaves = ids - parents
    return ids, parents, leaves, by_id

def process_mart(mart: str, all_ids, parents, leaves):
    mart_dir = ROOT/'artifacts/rd8/l2_classified'/mart
    matching_path = mart_dir/'matching_updates.jsonl'
    if not matching_path.exists():
        print(f'{mart}: matching_updates.jsonl 없음, skip')
        return
    rows = [json.loads(l) for l in matching_path.read_text(encoding='utf-8').splitlines() if l.strip()]
    fixed = 0
    pack_fixed = 0
    brand_fixed = 0
    nonleaf_count = 0
    nonleaf_rows = []
    for r in rows:
        # pack_unit_kind 채움
        if not r.get('pack_unit_kind'):
            uk = classify_unit_kind(r.get('pack_unit'))
            if uk:
                r['pack_unit_kind'] = uk
                pack_fixed += 1
        # brand 폴백
        b = r.get('brand')
        if not b or (isinstance(b, str) and b.strip() in ('', '브랜드없음', 'no_brand', 'null')):
            r['brand'] = MART_KO.get(mart, mart)
            brand_fixed += 1
        # category leaf 확인 (수정 X, 보고만)
        cid = r.get('category_id')
        if cid in parents:
            nonleaf_count += 1
            if len(nonleaf_rows) < 5:
                nonleaf_rows.append({'name': r.get('name_core') or r.get('name'), 'cat': cid})
    fixed = pack_fixed + brand_fixed
    out = mart_dir/'matching_updates_postfixed.jsonl'
    out.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    print(f'\n=== {mart} ===')
    print(f'  rows={len(rows)} postfixed={fixed} (pack_unit_kind +{pack_fixed}, brand fallback +{brand_fixed})')
    print(f'  non-leaf category_id 잔존={nonleaf_count}  (LLM 재분류 필요)')
    for ex in nonleaf_rows:
        print(f'    ex: {ex["name"]} -> {ex["cat"]}')
    print(f'  postfixed 파일: {out}')

def main():
    all_ids, parents, leaves, by_id = load_cat_tree()
    print(f'categories total={len(all_ids)} leaves={len(leaves)} non-leaf={len(parents & all_ids)}')
    for mart in ('costco','homeplus','lottemart'):
        process_mart(mart, all_ids, parents, leaves)

if __name__ == '__main__':
    main()
