"""Numbered review packets: prepare from certified JSON, decide by number, check all rules.

Never opens SQLite. Decisions are source code inputs, not DB approval.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from catalog_harness import ROOT, preflight, read, require, safe_path, sha, code_hashes

REVIEWS = 'packages/db-admin/backend/services/numbered_reviews'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def named(root, name, prefix):
    require(bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', name)), 'Invalid packet name')
    return safe_path(root, f'{prefix}/{name}.json', prefix)


def prepare(name, mart, shelf, root=ROOT):
    state, _, baseline, _, _ = preflight(root)
    held = {rid for file in (root/REVIEWS).glob('*.json') for row in read(file)['rows'] for rid in row['raw_record_ids']}
    groups = {}
    for row in read(baseline/'classification-decisions.json'):
        if row['mart'] != mart or row['source_path'] != shelf or row['unified_category_id'] is not None or row['raw_record_id'] in held:
            continue
        key = (row['mart'], tuple(row['source_path_parts']), row['source_title'])
        item = groups.setdefault(key, {'mart':mart, 'source_path_parts':row['source_path_parts'], 'source_title':row['source_title'], 'raw_record_ids':[], 'source_row_sha256':{}})
        item['raw_record_ids'].append(row['raw_record_id'])
        item['source_row_sha256'][row['raw_record_id']] = digest(row)
    rows = [dict(row, number=index) for index, row in enumerate(groups.values(), 1)]
    require(bool(rows), 'No unreviewed candidates')
    packet = {'schema_version':1, 'baseline':state['baseline'], 'source_file_sha256':state['source_file_sha256'], 'rows':rows}
    path = named(root, name, '.debug-artifacts/review-packets')
    write_new(path, packet)
    for row in rows:
        print(f"{row['number']} | {row['source_title']} | observations={len(row['raw_record_ids'])}")
    print(f'packet={name} sha256={sha(path)}')


def parse_assignments(specs, holds, total):
    result = {}
    for leaf, reason, numbers in [(s.split('=',1)[0], '', s.split('=',1)[1]) for s in specs] + [(None, s.split('=',1)[0], s.split('=',1)[1]) for s in holds]:
        require(leaf is not None or bool(reason.strip()), 'Hold reason required')
        for token in numbers.split(','):
            number = int(token)
            require(1 <= number <= total and number not in result, 'Unknown or duplicate number')
            result[number] = (leaf, reason)
    require(set(result) == set(range(1,total+1)), 'Every candidate needs a decision or hold reason')
    return result


def decide(name, packet_sha, specs, holds, root=ROOT):
    state, _, baseline, _, _ = preflight(root)
    path = named(root, name, '.debug-artifacts/review-packets')
    require(sha(path) == packet_sha, 'Packet hash changed')
    packet = read(path)
    require(packet['baseline'] == state['baseline'] and packet['source_file_sha256'] == state['source_file_sha256'], 'Stale packet')
    source = {r['raw_record_id']:r for r in read(baseline/'classification-decisions.json')}
    assignments = parse_assignments(specs, holds, len(packet['rows']))
    sys.path[:0] = [str(root/'packages/shared'), str(root/'packages/db-admin/backend')]
    from services.initial_taxonomy import LEAVES
    leaves = {leaf.id for leaf in LEAVES}
    rows = []
    for row in packet['rows']:
        for rid in row['raw_record_ids']:
            require(rid in source and digest(source[rid]) == row['source_row_sha256'][rid], 'Source row changed')
            require(source[rid]['unified_category_id'] is None, 'Already classified')
            require((row['mart'],row['source_path_parts'],row['source_title']) == (source[rid]['mart'],source[rid]['source_path_parts'],source[rid]['source_title']), 'Packet context mismatch')
        leaf, reason = assignments[row['number']]
        require(leaf is None or leaf in leaves, 'Unknown leaf category')
        rows.append(dict(row, leaf=leaf, hold_reason=reason))
    document = dict(packet, packet_sha256=packet_sha, rows=rows)
    destination = named(root, name, REVIEWS)
    # Cross-packet conflicts are rejected before creating a source rule file.
    existing = {}
    for file in (root/REVIEWS).glob('*.json'):
        for row in read(file)['rows']:
            existing[(row['mart'],tuple(row['source_path_parts']),row['source_title'])] = row['leaf']
    for row in rows:
        key = (row['mart'],tuple(row['source_path_parts']),row['source_title'])
        require(key not in existing, 'Previously reviewed context; explicit revision required')
    write_new(destination, document)
    print(f'Created {destination.relative_to(root)}; decisions={len(rows)}; not DB-certified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('name'); p.add_argument('--mart',required=True); p.add_argument('--shelf',required=True)
    p = sub.add_parser('decide'); p.add_argument('name'); p.add_argument('--packet-sha',required=True); p.add_argument('--set',action='append',default=[]); p.add_argument('--hold',action='append',default=[])
    p = sub.add_parser('checkpoint'); p.add_argument('run_id'); p.add_argument('--next',required=True)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.name,args.mart,args.shelf)
    elif args.action == 'decide': decide(args.name,args.packet_sha,args.set,args.hold)
    else: checkpoint(args.run_id,args.next)


def checkpoint(run_id, next_task, root=ROOT):
    state, *_ = preflight(root)
    require('\n' not in next_task and len(next_task) <= 500, 'Next task must be one short line')
    out = safe_path(root,'.debug-artifacts/'+run_id,'.debug-artifacts')
    certificate = read(out/'checks-passed.json')
    require(certificate['status'] == 'checks_passed_not_published', 'Uncertified run')
    require(certificate['baseline'] == state['baseline'], 'Unexpected baseline')
    require(certificate['code_sha256'] == code_hashes(root), 'Code changed since certification')
    require(certificate['bundle_sha256'] == sha(out/'catalog-bundle.json'), 'Bundle changed')
    require(certificate['staging_sha256'] == sha(out/'staging.sqlite'), 'Staging changed')
    report = certificate['build_report']
    updated = dict(state, baseline=str(out.relative_to(root)).replace('\\','/'), included=report['included_observations'], unresolved=report['unresolved_observations'], next_task=next_task)
    content = f"# 재개점 — {run_id}\n\n- 인증 사본: `{updated['baseline']}/checks-passed.json`; 운영 DB 미적용·공개 미승인.\n- 적재 {updated['included']}, 미해결 {updated['unresolved']}; 상품군 {report['entity_counts']['products']}, 판매 페이지 {report['entity_counts']['source_listings']}.\n- 신규 관측 {len(certificate['new_included_ids'])}; 검사 결과·실행 로그는 인증 사본과 catalog-logs 참조.\n- 다음: {next_task}\n- 경로·보호 해시는 catalog-state.json 기준. 과거 보류는 numbered_reviews 및 이력 문서에서 해당 묶음만 검색.\n"
    # Preserve recovery inputs before updating the two small human-facing files.
    backup = root/'.debug-artifacts/checkpoint-backups'/run_id
    backup.mkdir(parents=True,exist_ok=False)
    for name in ('catalog-state.json','RESUME_CHECKPOINT.md'):
        (backup/name).write_bytes((root/'docs'/name).read_bytes())
    for name, value in [('catalog-state.json',json.dumps(updated,ensure_ascii=False,indent=2)+'\n'),('RESUME_CHECKPOINT.md',content)]:
        target = root/'docs'/name
        temp = target.with_suffix(target.suffix+'.tmp')
        with temp.open('x',encoding='utf-8') as stream: stream.write(value)
        temp.replace(target)
    print(f'Checkpoint updated: {run_id}; backup={backup.relative_to(root)}')


if __name__ == '__main__': main()
