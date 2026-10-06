"""Shared exact-context rules produced by the numbered review workflow."""
import json
from functools import lru_cache
from pathlib import Path
from core.reviewed_source_evidence import source_review_matches

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


@lru_cache(maxsize=1)
def source_reviews():
    """Additional listing evidence required by explicitly source-bound reviews."""
    result = {}
    for path in sorted(DIRECTORY.glob('*.json')):
        for row in json.loads(path.read_text(encoding='utf-8'))['rows']:
            urls = row.get('required_source_urls')
            if urls is None:
                continue
            if not row['leaf'] or not isinstance(urls, list) or not urls or not all(isinstance(url, str) and url for url in urls):
                raise ValueError(f'Invalid source-bound review: {path}')
            key = (row['mart'], tuple(row['source_path_parts']), row['source_title'])
            required = {'source_urls': sorted(set(urls)), 'source_fields': row.get('required_source_fields', {})}
            if not isinstance(required['source_fields'], dict):
                raise ValueError(f'Invalid source fields: {path}')
            if key in result and result[key] != required:
                raise ValueError(f'Conflicting source-bound review: {path}')
            result[key] = required
    return result


def reviewed_numbered_leaf(evidence):
    key = (evidence['mart'], tuple(evidence['source_path_parts']), evidence['source_title'])
    required = source_reviews().get(key)
    actual = {'source_urls': evidence.get('source_urls', ()), 'source_fields': evidence.get('source_review_fields', {})}
    if required is not None and not source_review_matches(actual, required):
        return None
    return rules().get(key)


@lru_cache(maxsize=1)
def path_reviews():
    result={}
    for path in sorted(DIRECTORY.glob('*.json')):
        for row in json.loads(path.read_text(encoding='utf-8'))['rows']:
            review=row.get('rejected_path_evidence')
            if review and row['leaf'] and review.get('reason','').strip():
                key=(row['mart'],tuple(row['source_path_parts']),row['source_title'])
                if key in result: raise ValueError('Duplicate path review')
                result[key]=review['category_id']
    return result


def reviewed_rejected_path(evidence):
    return path_reviews().get((evidence['mart'],tuple(evidence['source_path_parts']),evidence['source_title']))


@lru_cache(maxsize=1)
def category_reviews():
    result = {}
    for path in sorted(DIRECTORY.glob('*.json')):
        for row in json.loads(path.read_text(encoding='utf-8'))['rows']:
            reviews = row.get('rejected_category_evidence', [])
            if reviews and row['leaf']:
                key = (row['mart'], tuple(row['source_path_parts']), row['source_title'])
                if key in result:
                    raise ValueError('Duplicate category review')
                result[key] = {item['category_id']: item['reason'] for item in reviews}
    return result


def reviewed_rejected_categories(evidence):
    return category_reviews().get((evidence['mart'], tuple(evidence['source_path_parts']), evidence['source_title']), {})


@lru_cache(maxsize=1)
def form_reviews():
    """Audited declared forms, with independent quantity holds when necessary."""
    result = {}
    for path in sorted(DIRECTORY.glob('*.json')):
        for row in json.loads(path.read_text(encoding='utf-8'))['rows']:
            review = row.get('confirmed_product_form')
            if review is None:
                continue
            if (not row['leaf'] or not row.get('required_source_urls')
                    or not isinstance(review, dict) or not review.get('reason')
                    or not review.get('decision_sha256')):
                raise ValueError(f'Invalid confirmed form review: {path}')
            key = (row['mart'], tuple(row['source_path_parts']), row['source_title'])
            if key in result:
                raise ValueError(f'Duplicate confirmed form review: {path}')
            result[key] = {**review, 'leaf': row['leaf'],
                           'quantity_hold_reason': row.get('quantity_hold_reason')}
    return result


def reviewed_product_form(evidence):
    key = (evidence['mart'], tuple(evidence['source_path_parts']), evidence['source_title'])
    review = form_reviews().get(key)
    return review if review and reviewed_numbered_leaf(evidence) == review['leaf'] else None
