import json, pathlib, yaml, collections, sys

tree = yaml.safe_load(pathlib.Path('packages/shared/data/categories_rd8.yaml').read_text(encoding='utf-8'))
leafs = set()
def walk(nodes):
    for n in nodes:
        ch = n.get('children') or []
        if ch:
            walk(ch)
        else:
            leafs.add(n['id'])
roots = tree.get('categories') or tree.get('tree') or tree
if isinstance(roots, dict):
    roots = list(roots.values())
walk(roots)
print('total leafs:', len(leafs))

for m in ('costco', 'homeplus', 'lottemart'):
    p = pathlib.Path(f'artifacts/rd8/l2_classified/{m}/matching_updates_final.jsonl')
    rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    bad = [r for r in rows if r.get('category_id') not in leafs]
    miss_kind = [r for r in rows if not r.get('pack_unit_kind')]
    miss_brand = [r for r in rows if not r.get('brand')]
    dist = collections.Counter(r.get('category_id') for r in rows)
    print(f'\n== {m} == n={len(rows)} non-leaf={len(bad)} no-kind={len(miss_kind)} no-brand={len(miss_brand)}')
    for c, k in dist.most_common(10):
        print(f'  {k:4d} {c}')
    if bad[:5]:
        print('  bad samples:')
        for r in bad[:5]:
            print('   ', r.get('name') or r.get('name_core'), '->', r.get('category_id'))
    # spot-check cola/cider/beer/manduu
    samples = ['콜라', '사이다', '맥주', '만두', '우유']
    for kw in samples:
        hits = [r for r in rows if kw in (r.get('name') or r.get('name_core') or '')]
        cats = collections.Counter(r.get('category_id') for r in hits)
        if hits:
            print(f'  [{kw}] {len(hits)}건 -> {dict(cats)}')
