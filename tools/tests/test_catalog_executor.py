import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog_executor as executor


def setup(tmp_path, monkeypatch):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/catalog-state.json').write_text(json.dumps({'baseline': '.debug-artifacts/base'}))
    (tmp_path / '.debug-artifacts').mkdir()
    baseline = tmp_path / '.debug-artifacts/base'
    baseline.mkdir()
    (baseline / 'catalog-bundle.json').write_text(json.dumps({
        'build_report': {'entity_counts': {'products': 4, 'source_listings': 5}}}))
    monkeypatch.setattr(executor, 'code_hashes', lambda root: {'file.py': 'abc'})
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'action': 'certify', 'run_id': 'initial-catalog-test',
                                'baseline': '.debug-artifacts/base', 'code_sha256': {'file.py': 'abc'}}))
    return plan


def test_stale_pin_rejected_before_execution(tmp_path, monkeypatch):
    plan = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(executor.subprocess, 'run', lambda *a, **k: pytest.fail('harness started'))
    data = json.loads(plan.read_text())
    data['code_sha256']['file.py'] = 'stale'
    plan.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Stale code hashes'):
        executor.run(plan, tmp_path)


def test_create_plan_pins_current_state_and_never_overwrites(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    path = tmp_path / executor.create_plan('initial-catalog-created', tmp_path)
    data = json.loads(path.read_text())
    assert data == {'action': 'certify', 'run_id': 'initial-catalog-created',
                    'baseline': '.debug-artifacts/base', 'code_sha256': {'file.py': 'abc'}}
    with pytest.raises(FileExistsError):
        executor.create_plan('initial-catalog-created', tmp_path)
    assert json.loads(path.read_text()) == data


def test_existing_log_cannot_be_overwritten(tmp_path, monkeypatch):
    plan = setup(tmp_path, monkeypatch)
    log = tmp_path / '.debug-artifacts/catalog-verify-logs/initial-catalog-test'
    log.mkdir(parents=True)
    (log / 'keep').write_text('original')
    with pytest.raises(ValueError, match='never overwrite'):
        executor.run(plan, tmp_path)
    assert (log / 'keep').read_text() == 'original'


def test_failure_reports_bounded_tail_and_stops(tmp_path, monkeypatch):
    plan = setup(tmp_path, monkeypatch)
    calls = []
    def fake(command, cwd, stdout, stderr):
        calls.append(command)
        stdout.write('old\n' * 30 + 'error detail\n')
        return type('Result', (), {'returncode': 7})()
    monkeypatch.setattr(executor.subprocess, 'run', fake)
    report = executor.run(plan, tmp_path)
    assert report['status'] == 'failed' and report['step'] == 'preflight'
    assert report['exit_code'] == 7 and 'error detail' in report['detail']
    assert len(report['detail'].splitlines()) <= 15 and len(calls) == 1
    assert json.loads((tmp_path / report['report']).read_text()) == report


def test_run_failure_extracts_assertions_from_step_log(tmp_path, monkeypatch):
    plan = setup(tmp_path, monkeypatch)
    calls = []
    def fake(command, cwd, stdout, stderr):
        calls.append(command)
        if 'run' in command:
            step = tmp_path / '.debug-artifacts/catalog-logs/initial-catalog-test/01.log'
            step.parent.mkdir(parents=True)
            step.write_text('noise\n' * 90 + 'FAILED test_example.py::test_rule\nE   AssertionError: expected 2\n' + 'traceback\n' * 20)
            stdout.write('Traceback only\n')
            return type('Result', (), {'returncode': 1})()
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(executor.subprocess, 'run', fake)
    report = executor.run(plan, tmp_path)
    assert report['status'] == 'failed' and report['step'] == 'run'
    assert 'FAILED test_example' in report['detail']
    assert 'AssertionError: expected 2' in report['detail']
    assert 'traceback' not in report['detail']
    assert report['log'].endswith('01.log') and len(calls) == 2


def test_success_requires_and_reports_certificate(tmp_path, monkeypatch):
    plan = setup(tmp_path, monkeypatch)
    calls = []
    def fake(command, cwd, stdout, stderr):
        calls.append(command)
        if 'run' in command:
            output = tmp_path / '.debug-artifacts/initial-catalog-test'
            output.mkdir()
            (output / 'checks-passed.json').write_text(json.dumps({
                'status': 'checks_passed_not_published', 'run_id': 'initial-catalog-test',
                'baseline': '.debug-artifacts/base', 'code_sha256': {'file.py': 'abc'},
                'new_included_ids': ['a', 'b'],
                'build_report': {'included_observations': 12, 'unresolved_observations': 3,
                                 'entity_counts': {'products': 7, 'source_listings': 9}}}))
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(executor.subprocess, 'run', fake)
    report = executor.run(plan, tmp_path)
    assert report['status'] == 'passed' and report['added_observations'] == 2
    assert report['included'] == 12 and report['unresolved'] == 3
    assert report['added_products'] == 3 and report['added_listings'] == 4
    assert len(calls) == 2
    assert json.loads((tmp_path / report['report']).read_text()) == report
