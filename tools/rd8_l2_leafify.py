"""
RD8 L2 산출의 non-leaf category_id를 categories_rd8.yaml의 keyword_seeds 기반으로
deterministic leaf로 재배치한다. 매칭 안 되는 row만 escalation_queue.jsonl로 분리.

알고리즘:
1. 카테고리 트리에서 부모-자식 인덱스, leaf 집합, 각 leaf의 keyword_seeds 적재.
2. 각 row에 대해: 현 category_id가 비-leaf이면, 후손 leaf들의 keyword_seeds 중 name_core/name 안에 등장하는 키워드 길이 가장 긴 매칭의 leaf 선택.
3. 매칭 0이면 escalation_queue.jsonl로 분리.
4. 매칭 결과는 matching_updates_leafified.jsonl로 저장.
"""
from __future__ import annotations
import json, sys, re
from pathlib import Path
import yaml
import collections

ROOT = Path(__file__).resolve().parent.parent

def load_tree():
    data = yaml.safe_load((ROOT/'packages/shared/data/categories_rd8.yaml').read_text(encoding='utf-8'))
    cat_list = data['categories'] if isinstance(data, dict) and 'categories' in data else data
    by_id = {}
    children = collections.defaultdict(list)
    parents = set()
    for c in cat_list:
        cid = c['id']
        by_id[cid] = c
        p = c.get('parent')
        if p:
            children[p].append(cid)
            parents.add(p)
    leaves = set(by_id) - parents

    # descendants 캐시 (leaf only)
    def desc_leaves(cid, acc=None):
        if acc is None: acc = []
        if cid in leaves:
            acc.append(cid); return acc
        for ch in children.get(cid, []):
            desc_leaves(ch, acc)
        return acc
    return by_id, children, leaves, parents, desc_leaves

def collect_keywords(by_id, descs):
    """descendants leaf 각각의 (keyword, leaf_id, length) 리스트 반환"""
    out = []
    for lid in descs:
        c = by_id.get(lid, {})
        for kw in (c.get('keyword_seeds') or []):
            kw_s = str(kw).strip()
            if kw_s:
                out.append((kw_s.lower(), lid, len(kw_s)))
        # display_name도 매칭 키워드로 추가
        dn = c.get('display_name_ko') or c.get('display_name') or ''
        if dn:
            out.append((dn.lower().strip(), lid, len(dn)))
    # 길이 desc 정렬 (가장 긴 키워드 먼저 매칭)
    out.sort(key=lambda x: -x[2])
    return out

def process_mart(mart: str, by_id, leaves, parents, desc_leaves):
    mart_dir = ROOT/'artifacts/rd8/l2_classified'/mart
    src = mart_dir/'matching_updates_postfixed.jsonl'
    if not src.exists():
        src = mart_dir/'matching_updates.jsonl'
    if not src.exists():
        print(f'{mart}: source 없음')
        return
    rows = [json.loads(l) for l in src.read_text(encoding='utf-8').splitlines() if l.strip()]

    reassigned = 0
    already_leaf = 0
    escalated = []
    cache = {}  # parent_id -> keyword index

    for r in rows:
        cid = r.get('category_id')
        if cid in leaves:
            already_leaf += 1
            continue
        if cid not in parents:
            # invalid 또는 누락 — escalate
            r['_reason'] = 'invalid_or_missing_category_id'
            escalated.append(r); continue
        # parent의 후손 leaf 집합 기반 키워드 매칭
        if cid not in cache:
            cache[cid] = collect_keywords(by_id, desc_leaves(cid))
        kw_idx = cache[cid]

        name = (r.get('name_core') or r.get('name') or '').lower()
        aliases = ' '.join(r.get('aliases') or []).lower()
        haystack = name + ' ' + aliases

        best = None
        for kw, lid, n in kw_idx:
            if kw and kw in haystack:
                best = lid; break  # 가장 긴 키워드부터 매칭 (사전 정렬)
        if best:
            r['category_id'] = best
            r.setdefault('_leafify_reason', f'kw_match_from_{cid}')
            reassigned += 1
        else:
            r['_reason'] = f'no_kw_match_under_{cid}'
            escalated.append(r)

    out = mart_dir/'matching_updates_leafified.jsonl'
    out.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows if r not in escalated),
                   encoding='utf-8')
    esc = mart_dir/'escalation_queue.jsonl'
    esc.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in escalated),
                   encoding='utf-8')

    # 분포 재확인
    final_rows = [r for r in rows if r not in escalated]
    cats = collections.Counter(r.get('category_id') for r in final_rows)
    nonleaf_final = sum(1 for c in cats if c in parents)

    print(f'\n=== {mart} ===')
    print(f'  total={len(rows)}  already_leaf={already_leaf}  reassigned={reassigned}  escalated={len(escalated)}')
    print(f'  최종 non-leaf 잔존={nonleaf_final}')
    print(f'  Top10 final:')
    for cid, n in cats.most_common(10):
        mark = ' !LEAF' if cid in parents else ''
        print(f'    {n:4d}  {cid}{mark}')

def main():
    by_id, children, leaves, parents, desc_leaves = load_tree()
    for mart in ('costco','homeplus','lottemart'):
        process_mart(mart, by_id, leaves, parents, desc_leaves)

if __name__ == '__main__':
    main()
