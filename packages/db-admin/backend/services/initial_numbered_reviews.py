"""Shared exact-context rules produced by the numbered review workflow."""
import json
from functools import lru_cache
from pathlib import Path

DIRECTORY = Path(__file__).with_name('numbered_reviews')


@lru_cache(maxsize=1)
def rules():
    result = {}
    for path in sorted(DIRECTORY.glob('*.json')):
        doc = json.loads(path.read_text(encoding='utf-8'))
        if doc['schema_version'] != 1:
            raise ValueError(f'Unsupported review schema: {path}')
        for row in doc['rows']:
            key = (row['mart'], tuple(row['source_path_parts']), row['source_title'])
            leaf = row['leaf']
            if key in result and result[key] != leaf:
                raise ValueError(f'Conflicting numbered review: {path}')
            result[key] = leaf
    return result


def reviewed_numbered_leaf(evidence):
    return rules().get((evidence['mart'], tuple(evidence['source_path_parts']), evidence['source_title']))
