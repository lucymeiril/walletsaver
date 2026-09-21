import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog_batch as batch
import catalog_review as review


def fixture_job(root, monkeypatch, names=('one', 'two')):
    packets = []
    calls = []
    for index, name in enumerate(names, 1):
        packet = review.named(root, name, '.debug-artifacts/review-packets')
        review.write_new(packet, {'rows': [{'number': 1, 'mart': 'mart',
            'source_path_parts': [name], 'source_title': name}]})
        proposal = review.named(root, name, '.debug-artifacts/review-proposals')
        review.write_new(proposal, {'packet_sha256': review.sha(packet),
            'assignments': {} if index == 2 else {'leaf': [1]},
            'holds': {'unclear': [1]} if index == 2 else {}})
        packets.append({'name': name, 'path': packet.relative_to(root).as_posix(),
            'sha256': review.sha(packet), 'output': proposal.relative_to(root).as_posix()})
    job = root/'.debug-artifacts/review-jobs/job.json'
    review.write_new(job, {'leaves': {'leaf': 'Leaf'}, 'packets': packets, 'constraints': []})

    def proposal(name, proposal_sha, apply=False, root=None):
        path = review.named(root, name, '.debug-artifacts/review-proposals')
        if review.sha(path) != proposal_sha:
            raise ValueError('Proposal hash changed')
        document = json.loads(path.read_text())
        review.proposal_specs(document)
        calls.append((name, apply))
        if apply:
            review.write_new(review.named(root, name, review.REVIEWS), {'name': name})
    monkeypatch.setattr(batch.review, 'proposal', proposal)
    return job, calls


def test_inspect_rejects_changed_packet_and_proposal_hashes(tmp_path, monkeypatch):
    job, _ = fixture_job(tmp_path, monkeypatch)
    packet = tmp_path/'.debug-artifacts/review-packets/one.json'
    packet.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Packet hash changed'):
        batch.inspect_job(job, root=tmp_path)

    job, _ = fixture_job(tmp_path/'fresh', monkeypatch)
    proposal = tmp_path/'fresh/.debug-artifacts/review-proposals/one.json'
    document = json.loads(proposal.read_text())
    document['packet_sha256'] = 'a' * 64
    proposal.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError, match='Proposal packet hash changed'):
        batch.inspect_job(job, root=tmp_path/'fresh')


def test_invalid_later_proposal_causes_zero_rule_writes(tmp_path, monkeypatch):
    job, calls = fixture_job(tmp_path, monkeypatch)
    proposal = tmp_path/'.debug-artifacts/review-proposals/two.json'
    document = json.loads(proposal.read_text())
    document['holds'] = {'unclear': []}
    proposal.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError, match='integer numbers'):
        batch.inspect_job(job, root=tmp_path)
    assert calls == [('one', False)]
    assert not (tmp_path/review.REVIEWS).exists()


def test_apply_refuses_any_existing_destination_before_writes(tmp_path, monkeypatch):
    job, calls = fixture_job(tmp_path, monkeypatch)
    manifest = tmp_path/'.debug-artifacts/review-manifests/job.json'
    batch.inspect_job(job, manifest, tmp_path)
    calls.clear()
    existing = review.named(tmp_path, 'two', review.REVIEWS)
    review.write_new(existing, {'existing': True})
    with pytest.raises(ValueError, match='destination already exists'):
        batch.apply_job(job, manifest, tmp_path)
    assert calls == [('one', False), ('two', False)]
    assert not review.named(tmp_path, 'one', review.REVIEWS).exists()
    assert json.loads(existing.read_text()) == {'existing': True}


def test_apply_success_writes_every_rule_and_logs_output(tmp_path, monkeypatch, capsys):
    job, calls = fixture_job(tmp_path, monkeypatch)
    manifest = tmp_path/'.debug-artifacts/review-manifests/job.json'
    batch.inspect_job(job, manifest, tmp_path)
    summary = json.loads(capsys.readouterr().out)
    assert summary == {'assignments': 1, 'candidates': 2, 'hold_kinds': {'unclear': 1},
        'holds': 1, 'manifest': '.debug-artifacts/review-manifests/job.json', 'packets': 2}
    calls.clear()
    result = batch.apply_job(job, manifest, tmp_path)
    assert calls == [('one', False), ('two', False), ('one', True), ('two', True)]
    assert all(review.named(tmp_path, name, review.REVIEWS).is_file() for name in ('one', 'two'))
    assert (tmp_path/result['log']).is_file()


def test_apply_rejects_proposal_content_change_after_inspect(tmp_path, monkeypatch):
    job, calls = fixture_job(tmp_path, monkeypatch)
    manifest = tmp_path/'.debug-artifacts/review-manifests/job.json'
    batch.inspect_job(job, manifest, tmp_path)
    calls.clear()
    proposal = tmp_path/'.debug-artifacts/review-proposals/one.json'
    document = json.loads(proposal.read_text())
    document['assignments'] = {}
    document['holds'] = {'changed after inspection': [1]}
    proposal.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError, match='Manifest or inspected inputs changed'):
        batch.apply_job(job, manifest, tmp_path)
    assert calls == [('one', False), ('two', False)]
    assert not (tmp_path/review.REVIEWS).exists()


def test_inspect_rejects_leaf_outside_delegated_job(tmp_path, monkeypatch):
    job, calls = fixture_job(tmp_path, monkeypatch)
    proposal = tmp_path/'.debug-artifacts/review-proposals/one.json'
    document = json.loads(proposal.read_text())
    document['assignments'] = {'other.global.leaf': [1]}
    proposal.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError, match='leaf outside job'):
        batch.inspect_job(job, root=tmp_path)
    assert calls == []
