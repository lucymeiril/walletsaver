"""Independently accepted external proposals, pinned to listing/title/path.

Unreviewed handoff proposals are NEVER loaded by the classifier.
"""
import json
from pathlib import Path

ROWS = json.loads(Path(__file__).with_name('reviewed_chat_batch_20260912.json').read_text(encoding='utf-8'))
ROWS += json.loads(Path(__file__).with_name('reviewed_chat_batch_pass43.json').read_text(encoding='utf-8'))
ROWS += json.loads(Path(__file__).with_name('reviewed_chat_batch_pass44.json').read_text(encoding='utf-8'))
LOOKUP = {(r['mart'],r['source_record_key'],r['source_title'],tuple(r['source_path_parts'])):r['leaf'] for r in ROWS}
assert len(LOOKUP) == len(ROWS), 'Duplicate accepted review key'


def reviewed_chat_leaf(record, evidence):
    return LOOKUP.get((evidence['mart'], str(record.get('source_record_key') or ''), evidence['source_title'], tuple(evidence['source_path_parts'])))
