"""Execute a data-only preparation plan using the existing guarded commands."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from catalog_review import ROOT, named, read, require, sha


def inputs(plan_path, root=ROOT):
    plan = read(plan_path)
    require(set(plan) == {'action', 'name', 'shelves', 'leaf_prefixes'}, 'Invalid plan fields')
    require(plan['action'] == 'prepare', 'Only prepare is supported')
    name = plan['name']
    job = named(root, name, '.debug-artifacts/review-jobs')
    require(isinstance(plan['shelves'], list) and 0 < len(plan['shelves']) <= 100, 'Invalid shelves')
    require(all(isinstance(p, str) and p for p in plan['leaf_prefixes']), 'Invalid prefixes')
    require(bool(plan['leaf_prefixes']), 'Missing prefixes')
    packets = []
    commands = []
    for index, shelf in enumerate(plan['shelves'], 1):
        require(set(shelf) == {'mart', 'shelf'} and all(isinstance(v, str) and v for v in shelf.values()), 'Invalid shelf')
        packet_name = f'{name}-{index:02d}'
        packets.append(named(root, packet_name, '.debug-artifacts/review-packets'))
        commands.append(['py', 'tools/catalog_review.py', 'prepare', packet_name,
                         '--mart', shelf['mart'], '--shelf', shelf['shelf']])
    command = ['py', 'tools/catalog_job.py', name]
    for packet in packets:
        command.extend(['--packet', packet.stem])
    for prefix in plan['leaf_prefixes']:
        command.extend(['--leaf-prefix', prefix])
    commands.append(command)
    return plan, job, packets, commands


def verify(plan_path, root=ROOT):
    plan, job_path, packets, commands = inputs(plan_path, root)
    job = read(job_path)
    require(len(job['packets']) == len(packets), 'Packet count mismatch')
    count = 0
    for expected, entry, shelf in zip(packets, job['packets'], plan['shelves']):
        require(entry['path'] == expected.relative_to(root).as_posix(), 'Packet path mismatch')
        require(entry['sha256'] == sha(expected), 'Packet hash mismatch')
        packet = read(expected)
        require(isinstance(packet['rows'], list) and packet['rows'], 'Invalid packet rows')
        require(all(row['mart'] == shelf['mart'] and ' > '.join(row['source_path_parts']) == shelf['shelf']
                    for row in packet['rows']), 'Shelf mismatch')
        count += len(packet['rows'])
    return {'status': 'verified', 'job': job_path.relative_to(root).as_posix(),
            'packets': len(packets), 'candidates': count, 'command_count': len(commands),
            'plan_utf8_bytes': plan_path.stat().st_size,
            'rendered_command_characters': sum(len(subprocess.list2cmdline(c)) for c in commands)}


def run(plan_path, root=ROOT):
    plan, job, packets, commands = inputs(plan_path, root)
    log_dir = root / '.debug-artifacts/operator-logs' / (plan['name'] + '-script')
    require(not any(p.exists() for p in [job, *packets, log_dir]), 'Destination exists; do not retry or overwrite')
    log_dir.mkdir(parents=True)
    for index, command in enumerate(commands, 1):
        with (log_dir / f'{index:02d}.log').open('x', encoding='utf-8') as stream:
            result = subprocess.run([sys.executable, *command[1:]], cwd=root, stdout=stream, stderr=subprocess.STDOUT)
        require(result.returncode == 0, f'Failed step {index}; see {log_dir / f"{index:02d}.log"}')
    report = verify(plan_path, root)
    with (log_dir / 'report.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps((verify if args.verify_only else run)(args.plan), ensure_ascii=False))
