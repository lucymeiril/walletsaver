import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog_prepare import inputs, run, verify
from catalog_review import sha


def fixture_plan(tmp_path):
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'action': 'prepare', 'name': 'example',
        'shelves': [{'mart': 'emart', 'shelf': 'A'}, {'mart': 'lottemart', 'shelf': 'B'}],
        'leaf_prefixes': ['food']}), encoding='utf-8')
    _, job, packets, _ = inputs(plan, tmp_path)
    job.parent.mkdir(parents=True)
    entries = []
    for index, packet in enumerate(packets):
        packet.parent.mkdir(parents=True, exist_ok=True)
        row = {'mart': ['emart', 'lottemart'][index], 'source_path_parts': [['A'], ['B']][index]}
        packet.write_text(json.dumps({'rows': [row] * (index + 3)}), encoding='utf-8')
        entries.append({'path': packet.relative_to(tmp_path).as_posix(), 'sha256': sha(packet)})
    job.write_text(json.dumps({'packets': entries}), encoding='utf-8')
    return plan, packets


def test_counts_rows_not_packet_objects(tmp_path):
    plan, _ = fixture_plan(tmp_path)
    assert verify(plan, tmp_path)['candidates'] == 7


def test_changed_packet_rejected(tmp_path):
    plan, packets = fixture_plan(tmp_path)
    packets[0].write_text('{}', encoding='utf-8')
    with pytest.raises(Exception, match='hash mismatch'):
        verify(plan, tmp_path)


def test_existing_outputs_cannot_be_reexecuted(tmp_path):
    plan, _ = fixture_plan(tmp_path)
    with pytest.raises(Exception, match='Destination exists'):
        run(plan, tmp_path)
