"""Inspect and apply a bounded catalog-review delegation job; never opens SQLite."""
import argparse
import contextlib
import io
import json
from collections import Counter
from pathlib import Path

import catalog_review as review

ROOT = review.ROOT
MANIFESTS = '.debug-artifacts/review-manifests'
LOGS = '.debug-artifacts/review-apply-logs'


def _contained_json(root, value, prefix):
    path = Path(value)
    if path.is_absolute():
        resolved = path.resolve()
        allowed = (root / prefix).resolve()
        review.require(resolved.is_relative_to(allowed) and resolved.parent == allowed,
                       f'Path must be a direct JSON child of {prefix}')
    else:
        resolved = review.safe_path(root, str(path), prefix)
        review.require(resolved.parent == (root / prefix).resolve(),
                       f'Path must be a direct JSON child of {prefix}')
    review.require(resolved.suffix == '.json', 'JSON path required')
    return resolved


def _proposal_document(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            review.require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def inspect_job(job_path, save=None, root=ROOT):
    root = root.resolve()
    job_path = _contained_json(root, job_path, '.debug-artifacts/review-jobs')
    job = review.read(job_path)
    review.require(isinstance(job, dict) and set(job) == {'leaves', 'packets', 'constraints'},
                   'Invalid job fields')
    review.require(isinstance(job['leaves'], dict) and bool(job['leaves']), 'Job has no leaves')
    review.require(isinstance(job['packets'], list) and bool(job['packets']), 'Job has no packets')
    names = [item.get('name') for item in job['packets'] if isinstance(item, dict)]
    review.require(len(names) == len(job['packets']) and len(names) == len(set(names)),
                   'Invalid or duplicate job packet')

    proposals = []
    hold_reasons = Counter()
    assigned = held = candidates = 0
    contexts = set()
    for item in job['packets']:
        review.require(set(item) == {'name', 'path', 'sha256', 'output'}, 'Invalid job packet fields')
        name = item['name']
        packet_path = review.named(root, name, '.debug-artifacts/review-packets')
        proposal_path = review.named(root, name, '.debug-artifacts/review-proposals')
        review.require(item['path'] == packet_path.relative_to(root).as_posix(), 'Unexpected packet path')
        review.require(item['output'] == proposal_path.relative_to(root).as_posix(), 'Unexpected proposal path')
        review.require(packet_path.is_file() and review.sha(packet_path) == item['sha256'],
                       f'Packet hash changed: {name}')
        proposal_hash = review.sha(proposal_path)
        document = _proposal_document(proposal_path)
        specs, holds = review.proposal_specs(document)
        review.require(set(document['assignments']) <= set(job['leaves']),
                       f'Proposal uses leaf outside job: {name}')
        review.require(document['packet_sha256'] == item['sha256'],
                       f'Proposal packet hash changed: {name}')

        packet = review.read(packet_path)
        candidates += len(packet['rows'])
        for row in packet['rows']:
            context = (row['mart'], tuple(row['source_path_parts']), row['source_title'])
            review.require(context not in contexts, 'Duplicate context across job packets')
            contexts.add(context)
        assigned += sum(len(numbers) for numbers in document['assignments'].values())
        for reason, numbers in document['holds'].items():
            hold_reasons[reason] += len(numbers)
            held += len(numbers)

        # The established proposal path supplies all authoritative packet, source,
        # leaf, completeness, and cross-rule validation. Silence its one-line output.
        with contextlib.redirect_stdout(io.StringIO()):
            review.proposal(name, proposal_hash, root=root)
        proposals.append({'name': name, 'sha256': proposal_hash,
                          'packet_sha256': document['packet_sha256']})

    manifest = {
        'schema_version': 1,
        'job': {'path': job_path.relative_to(root).as_posix(), 'sha256': review.sha(job_path)},
        'totals': {'packets': len(proposals), 'candidates': candidates,
                   'assignments': assigned, 'holds': held},
        'hold_reasons': dict(sorted(hold_reasons.items())),
        'proposals': proposals,
    }
    if save is not None:
        save_path = _contained_json(root, save, MANIFESTS)
        review.write_new(save_path, manifest)
    summary = dict(manifest['totals'])
    summary['hold_kinds'] = dict(sorted(Counter(
        reason.split(':', 1)[0].strip() for reason in hold_reasons
        for _ in range(hold_reasons[reason])
    ).items()))
    if save is not None:
        summary['manifest'] = save_path.relative_to(root).as_posix()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return manifest


def apply_job(job_path, manifest_path, root=ROOT):
    root = root.resolve()
    manifest_path = _contained_json(root, manifest_path, MANIFESTS)
    saved = review.read(manifest_path)
    with contextlib.redirect_stdout(io.StringIO()):
        current = inspect_job(job_path, root=root)
    review.require(saved == current, 'Manifest or inspected inputs changed')

    destinations = [review.named(root, item['name'], review.REVIEWS)
                    for item in current['proposals']]
    review.require(all(not path.exists() for path in destinations),
                   'Decision destination already exists')
    log_path = review.safe_path(
        root,
        f'{LOGS}/{manifest_path.stem}-{review.sha(manifest_path)[:12]}.log',
        '.debug-artifacts',
    )
    review.require(not log_path.exists(), 'Apply log already exists')

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('x', encoding='utf-8') as stream, contextlib.redirect_stdout(stream):
        for item in current['proposals']:
            review.proposal(item['name'], item['sha256'], apply=True, root=root)
    result = dict(current['totals'], applied=True, log=log_path.relative_to(root).as_posix())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    command = sub.add_parser('inspect')
    command.add_argument('--job', required=True)
    command.add_argument('--save')
    command = sub.add_parser('apply')
    command.add_argument('--job', required=True)
    command.add_argument('--manifest', required=True)
    args = parser.parse_args()
    if args.action == 'inspect':
        inspect_job(args.job, args.save)
    else:
        apply_job(args.job, args.manifest)


if __name__ == '__main__':
    main()
