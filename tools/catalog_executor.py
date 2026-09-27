"""Run one hash-pinned catalog certification through the guarded harness."""
import argparse
from collections import deque
import json
from pathlib import Path
import re
import subprocess
import sys

from catalog_harness import ROOT, code_hashes, output_path, read, require, safe_path


def inputs(plan_path, root=ROOT):
    plan = read(plan_path)
    require(set(plan) == {'action', 'run_id', 'baseline', 'code_sha256'}, 'Invalid plan fields')
    require(plan['action'] == 'certify', 'Only certify is supported')
    require(isinstance(plan['run_id'], str), 'Invalid run ID')
    output = output_path(root, plan['run_id'])
    require(isinstance(plan['baseline'], str), 'Invalid baseline pin')
    require(plan['baseline'] == read(root / 'docs/catalog-state.json')['baseline'], 'Stale baseline pin')
    hashes = code_hashes(root)
    require(isinstance(plan['code_sha256'], dict) and plan['code_sha256'] == hashes, 'Stale code hashes')
    logs = safe_path(root, '.debug-artifacts/catalog-verify-logs/' + plan['run_id'], '.debug-artifacts')
    require(not logs.exists(), 'Verification log exists: never overwrite or retry')
    return plan, output, logs


def tail(path):
    with path.open(encoding='utf-8', errors='replace') as stream:
        return ''.join(deque(stream, maxlen=15))[-2000:]


def failure_detail(root, run_id, harness_log):
    log_dir = safe_path(root, '.debug-artifacts/catalog-logs/' + run_id, '.debug-artifacts')
    if log_dir.is_dir():
        step_logs = sorted(p for p in log_dir.iterdir() if re.fullmatch(r'\d\d\.log', p.name))
        if step_logs:
            latest = step_logs[-1]
            with latest.open(encoding='utf-8', errors='replace') as stream:
                lines = list(deque(stream, maxlen=100))
            selected = [line.strip() for line in lines if re.search(r'FAILED|AssertionError|^E\s|short test summary|error:', line, re.I)]
            if selected:
                return latest.relative_to(root).as_posix(), '\n'.join(selected)[-2000:]
            return latest.relative_to(root).as_posix(), ''.join(lines[-15:])[-2000:]
    return harness_log.relative_to(root).as_posix(), tail(harness_log)


def create_plan(run_id, root=ROOT):
    output_path(root, run_id)
    logs = safe_path(root, '.debug-artifacts/catalog-verify-logs/' + run_id, '.debug-artifacts')
    require(not logs.exists(), 'Verification log exists: never overwrite or retry')
    path = safe_path(root, '.debug-artifacts/catalog-verify-plans/' + run_id + '.json', '.debug-artifacts')
    path.parent.mkdir(parents=True, exist_ok=True)
    plan = {'action': 'certify', 'run_id': run_id,
            'baseline': read(root / 'docs/catalog-state.json')['baseline'],
            'code_sha256': code_hashes(root)}
    with path.open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
    return path.relative_to(root).as_posix()


def run(plan_path, root=ROOT):
    plan, output, logs = inputs(plan_path, root)
    logs.mkdir(parents=True, exist_ok=False)
    report_path = logs / 'report.json'
    report = {'status': 'failed', 'run_id': plan['run_id'],
              'report': report_path.relative_to(root).as_posix()}
    try:
        for step, args in [('preflight', ['preflight']),
                           ('run', ['run', '--run-id', plan['run_id']])]:
            log = logs / (step + '.log')
            with log.open('x', encoding='utf-8') as stream:
                result = subprocess.run([sys.executable, 'tools/catalog_harness.py', *args],
                                        cwd=root, stdout=stream, stderr=subprocess.STDOUT)
            if result.returncode:
                detail_log, detail = failure_detail(root, plan['run_id'], log) if step == 'run' else (log.relative_to(root).as_posix(), tail(log))
                report.update(step=step, exit_code=result.returncode,
                              log=detail_log, detail=detail)
                return report
        certificate_path = output / 'checks-passed.json'
        require(certificate_path.is_file(), 'Harness returned without certificate')
        certificate = read(certificate_path)
        require(certificate.get('status') == 'checks_passed_not_published', 'Invalid certificate status')
        require(certificate.get('run_id') == plan['run_id'], 'Certificate run ID mismatch')
        require(certificate.get('baseline') == plan['baseline'], 'Certificate baseline mismatch')
        require(certificate.get('code_sha256') == plan['code_sha256'], 'Certificate code hashes mismatch')
        build = certificate['build_report']
        baseline_bundle = read(root / plan['baseline'] / 'catalog-bundle.json')
        old_counts = baseline_bundle['build_report']['entity_counts']
        counts = build['entity_counts']
        report = {'status': 'passed', 'run_id': plan['run_id'],
                  'certificate': certificate_path.relative_to(root).as_posix(),
                  'added_observations': len(certificate['new_included_ids']),
                  'added_products': counts['products'] - old_counts['products'],
                  'added_listings': counts['source_listings'] - old_counts['source_listings'],
                  'included': build['included_observations'],
                  'unresolved': build['unresolved_observations'],
                  'report': report_path.relative_to(root).as_posix()}
        return report
    except Exception as exc:
        report.update(step=report.get('step', 'certificate'), detail=str(exc)[:2000])
        return report
    finally:
        with report_path.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path, nargs='?')
    parser.add_argument('--create-plan', metavar='RUN_ID')
    args = parser.parse_args()
    require(bool(args.plan) != bool(args.create_plan), 'Specify one plan or --create-plan')
    if args.create_plan:
        print(json.dumps({'plan': create_plan(args.create_plan)}, ensure_ascii=False))
        sys.exit(0)
    result = run(args.plan)
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] != 'passed':
        sys.exit(1)
