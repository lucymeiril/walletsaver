"""Typed source-bound correction proposals for the existing catalog bundle route.

Original observations are immutable. Preview prepares a separate reviewed
projection; formal apply uses the existing bundle transaction and never creates
a new source collection timestamp.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math

from fastapi import HTTPException
from sqlalchemy import select

from core.catalog_quantity import normalize_catalog_package, package_pricing_measure
from core.promotion_semantics import comparable_transaction_or_none
from core.reviewed_source_evidence import (source_review_evidence, source_review_matches,
    source_correction_event_hash,source_correction_variant_hash,source_correction_proposal_hash,
    SOURCE_CORRECTION_HOLD_ISSUES)
from services.catalog_bundle import ENTITY_KEYS, SCHEMA_VERSION, validate_bundle
from services.initial_catalog_seed import _price
from storage.models import (MatchingEntry, NormalizedCanonicalProduct,
    NormalizedProductVariant, NormalizedSourceListing, NormalizedOfferEvent)


def _plain(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _row(value):
    return {c.name: _plain(deepcopy(getattr(value, c.name))) for c in value.__table__.columns
            if c.name not in {'created_at', 'updated_at'}}


def _digest(value):
    return hashlib.sha256(json.dumps(_plain(value), ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _context(session, product_id, variant_id, listing_id, event_id):
    rows = [session.get(model, key) for model, key in (
        (NormalizedCanonicalProduct, product_id), (NormalizedProductVariant, variant_id),
        (NormalizedSourceListing, listing_id), (NormalizedOfferEvent, event_id))]
    if any(row is None for row in rows):
        raise HTTPException(404, 'Selected normalized source observation not found')
    product, variant, listing, event = rows
    if (variant.public_product_id != product_id or listing.public_variant_id != variant_id
            or event.public_source_listing_id != listing_id):
        raise HTTPException(409, 'Selected product/variant/listing/event tuple changed; reselect')
    observations = (event.raw_evidence or {}).get('observations')
    if not isinstance(observations, list) or not observations:
        raise HTTPException(422, 'Original source observation is required for correction')
    for observation in observations:
        raw = observation.get('raw_payload') if isinstance(observation, dict) else None
        attrs = raw.get('attributes') or {} if isinstance(raw,dict) else {}
        if not isinstance(raw, dict) or not isinstance(attrs, dict):
            raise HTTPException(422, 'Original source hash/native URL binding is incomplete')
        native = raw.get('source_record_key') or attrs.get('source_record_key')
        native_conflict = any(layer.get('source_record_key') not in (None,listing.source_record_key)
            for layer in (raw,attrs))
        if (not isinstance(raw, dict) or observation.get('raw_payload_sha256') != _digest(raw)
                or native != listing.source_record_key or native_conflict
                or not source_review_matches(source_review_evidence(raw), {
                    'source_urls':[listing.source_url], 'source_fields':{}})):
            raise HTTPException(422, 'Original source hash/native URL binding is incomplete')
    return product, variant, listing, event, observations


def correction_prefill(session, product_id, variant_id, listing_id, event_id):
    product, variant, listing, event, observations = _context(
        session, product_id, variant_id, listing_id, event_id)
    binding = {'product':_row(product),'variant':_row(variant),
               'listing':_row(listing),'event':_row(event)}
    scope_issues = set()
    hold_supported = True
    for observation in observations:
        raw = observation['raw_payload']
        _,issues = normalize_catalog_package(raw,raw.get('attributes') or {},listing.source_title,
            category_id=product.unified_category_id)
        scope_issues.update(issues)
        hold_supported = hold_supported and bool(issues) and set(issues) <= SOURCE_CORRECTION_HOLD_ISSUES
    return {'public_product_id':product_id, 'public_variant_id':variant_id,
        'public_source_listing_id':listing_id,'public_offer_event_id':event_id,
        'binding_sha256':_digest(binding), 'source_title':listing.source_title,
        'source_url':listing.source_url, 'source_name':listing.source_name,
        'source_record_key':listing.source_record_key,
        'stored_specification':{key:getattr(variant,key) for key in
            ('package_quantity','package_unit','bundle_count','display_unit')},
        'stored_quote':event.price,'observed_at':_plain(event.crawled_at),
        'source_observations':[{'raw_record_id':item.get('raw_record_id'),
            'raw_payload_sha256':item['raw_payload_sha256']} for item in observations],
        'editable_fields':['package_quantity','package_unit','bundle_count','price'],
        'quantity_scope_issues':sorted(scope_issues),
        'quantity_scope_actions':['hold_unresolved'] if hold_supported else [],
        'mutation_workflow':'source-bound preview → formal catalog bundle apply → snapshot publish',
        'original_observation_immutable':True}


def correction_preview(session, product_id, selection, *, identity):
    allowed = {'public_variant_id','public_source_listing_id','public_offer_event_id',
               'binding_sha256','reason','package_quantity','package_unit','bundle_count','price','quantity_scope_action'}
    if set(selection) - allowed:
        raise HTTPException(422, 'Only selected source-bound correction fields are supported')
    reason = selection.get('reason')
    if not isinstance(reason,str) or not reason.strip() or len(reason) > 2000:
        raise HTTPException(422, 'Correction reason is required (maximum 2000 characters)')
    ids = [selection.get(key) for key in
        ('public_variant_id','public_source_listing_id','public_offer_event_id')]
    if any(not isinstance(key,str) or not key for key in ids):
        raise HTTPException(422, 'Exact variant/listing/event IDs are required')
    product, variant, listing, event, observations = _context(session,product_id,*ids)
    prefill = correction_prefill(session,product_id,*ids)
    if selection.get('binding_sha256') != prefill['binding_sha256']:
        raise HTTPException(409, 'Selected source context changed; reload before preview')
    action = selection.get('quantity_scope_action')
    if action not in (None,'hold_unresolved'):
        raise HTTPException(422,'Unsupported quantity scope action')
    hold = action == 'hold_unresolved'
    if hold and {'price','package_quantity','package_unit','bundle_count'} & selection.keys():
        raise HTTPException(422,'Quantity scope hold cannot supply price or specification values')
    scope_issues = set()
    package = price_fields = None
    for observation in observations:
        raw = observation['raw_payload']; attrs = raw.get('attributes') or {}
        candidate, issues = normalize_catalog_package(raw,attrs,listing.source_title,
            category_id=product.unified_category_id)
        fields, price_issues = _price(raw,attrs,listing.source_name,listing.source_title)
        if hold:
            if (not issues or not set(issues) <= SOURCE_CORRECTION_HOLD_ISSUES
                    or fields.get('price') != event.price or isinstance(event.price,bool)
                    or event.price is None or event.price <= 0):
                raise HTTPException(422, {'message':'Retained source does not prove an unresolved quantity scope hold',
                    'quantity_issues':issues})
            scope_issues.update(issues)
            package = {key:deepcopy(getattr(variant,key)) for key in
                ('package_quantity','package_unit','bundle_count','display_unit','standard_unit','attributes')}
            price_fields = {key:getattr(event,key) for key in
                ('price','original_price','discount_rate','price_state','promotion_type','event_name')}
            price_fields['promotion_conditions'] = deepcopy((event.raw_evidence or {}).get('promotion_conditions') or {})
            continue
        if candidate is None or issues or 'sale_price_missing_or_invalid' in price_issues:
            raise HTTPException(422, {'message':'Retained source does not prove this correction',
                'quantity_issues':issues,'price_issues':price_issues})
        if package is not None and (_digest(candidate) != _digest(package) or _digest(fields) != _digest(price_fields)):
            raise HTTPException(422, 'Original observations conflict; formal source review is required')
        package, price_fields = candidate, fields
    package_keys = {'package_quantity','package_unit','bundle_count'}
    if package_keys & selection.keys():
        if not package_keys <= selection.keys():
            raise HTTPException(422, 'Quantity, unit and count must be reviewed together')
        for key in package_keys:
            value = selection[key]
            if isinstance(value,bool) or value != package.get(key):
                raise HTTPException(422, f'{key} differs from the retained source declaration')
        if type(selection['bundle_count']) is not int:
            raise HTTPException(422, 'Bundle count must be an explicit positive integer')
    if 'price' in selection:
        amount = selection['price']
        if (isinstance(amount,bool) or not isinstance(amount,(int,float)) or not math.isfinite(amount)
                or amount <= 0 or amount != price_fields['price']):
            raise HTTPException(422, 'Price differs from the immutable source quote')
    specification_changed = any(package.get(key) != getattr(variant,key) for key in package_keys)
    price_changed = price_fields['price'] != event.price
    proved_base_role = not hold and price_fields['promotion_conditions'].get('source_base_quote_only') is True
    if not price_changed and not proved_base_role:
        price_fields = {**price_fields, **{key:getattr(event,key) for key in
            ('promotion_type','price_state','original_price','discount_rate','event_name')},
            'promotion_conditions':deepcopy((event.raw_evidence or {}).get('promotion_conditions') or {})}
    price_fields['valid_from'] = _plain(event.valid_from)
    price_fields['valid_to'] = _plain(event.valid_to)
    transaction = None if hold else comparable_transaction_or_none(current_price=price_fields['price'],
        promotion_type=price_fields['promotion_type'],promotion_conditions=price_fields['promotion_conditions'])
    measure = package_pricing_measure(package)
    rate = round(transaction[0]*100/(measure[0]*transaction[1]),4) if transaction and measure else None
    per100g = rate if measure and measure[1]=='g' else None
    role_changed = (any(price_fields.get(key) != getattr(event,key) for key in
        ('promotion_type','price_state','original_price','discount_rate','event_name'))
        or _digest(price_fields['promotion_conditions']) != _digest((event.raw_evidence or {}).get('promotion_conditions') or {})
        or rate != event.standard_unit_price or per100g != event.price_per_100g)
    if hold:
        previous_hold = (event.audit_provenance or {}).get('source_correction_lineage') or {}
        role_changed = role_changed or event.offer_state != 'pending_review' or previous_hold.get('quantity_scope_action') != action
    rules = list(session.scalars(select(MatchingEntry).where(MatchingEntry.public_variant_id == variant.public_variant_id)))
    if specification_changed and any(rule.source == 'human' for rule in rules):
        raise HTTPException(409, {'message':'Human matching rule requires formal mapping review',
            'mutation_workflow':'/api/catalog-bundles','affected_match_keys':[r.match_key for r in rules if r.source=='human']})
    if specification_changed and session.scalar(select(NormalizedSourceListing.public_source_listing_id).where(
            NormalizedSourceListing.public_variant_id == variant.public_variant_id,
            NormalizedSourceListing.public_source_listing_id != listing.public_source_listing_id).limit(1)):
        raise HTTPException(409, {'message':'Shared variant requires multi-source formal review',
            'mutation_workflow':'/api/catalog-bundles','public_variant_id':variant.public_variant_id})
    if not specification_changed and not price_changed and not role_changed:
        return {'has_changes':False,'prefill':prefill,'source_specification':package,
            'source_price':price_fields,'quantity_scope_action':action,'quantity_scope_reasons':sorted(scope_issues),
            'source_specification_status':'unresolved_scope_historical_literal' if hold else 'source_supported',
            'validation':{'ok':True,'scope':'source_bound_no_change','formal_bundle_required':False,
                          'errors':[],'warnings':[]},
            'applied':False,'snapshot_published':False}
    proposal = {'version':1,'status':'reviewed_candidate','projection_kind':'source_interpretation_correction',
        'observation_kind':'source_interpretation_correction',
        'public_product_id':product_id,'public_source_listing_id':listing.public_source_listing_id,
        'source_name':listing.source_name,'source_record_key':listing.source_record_key,
        'source_url':listing.source_url,'original_event_id':event.public_offer_event_id,
        'original_event_sha256':source_correction_event_hash(_row(event)),
        'original_observations_sha256':_digest(observations),'original_quote':event.price,
        'observed_at':_plain(event.crawled_at),
        'original_variant_id':variant.public_variant_id,'original_variant_sha256':source_correction_variant_hash(_row(variant)),
        'unified_category_id':product.unified_category_id,'source_binding_sha256':prefill['binding_sha256'],
        'reason':reason.strip(),'reviewed_by':str(identity.get('sub') or identity.get('email') or 'moderator'),
        'selection_sha256':_digest(selection),'original_observation_immutable':True}
    if hold:
        proposal.update(quantity_scope_action=action,quantity_scope_reasons=sorted(scope_issues))
    correction_key = _digest({'binding':prefill['binding_sha256'],'package':package,'price':price_fields,
                             'quantity_scope_action':action,'quantity_scope_reasons':sorted(scope_issues)})
    variant_id = 'var-corrected-'+correction_key[:32] if specification_changed else variant.public_variant_id
    bundle = {'schema_version':SCHEMA_VERSION,'run_id':'source-correction-'+correction_key,
              **{key:[] for key in ENTITY_KEYS}}
    if specification_changed:
        bundle['variants'] = [{**_row(variant),**package,'public_variant_id':variant_id,
            'attributes':{**(package.get('attributes') or {}),'source_correction_lineage':proposal},'is_active':True}]
        bundle['source_listings'] = [{**_row(listing),'public_variant_id':variant_id}]
        for rule in rules:
            bundle['match_rules'].append({'match_key':rule.match_key,'public_product_id':product_id,
                'public_variant_id':variant_id,'confidence':rule.confidence,'source':rule.source,
                'keyword_ids':deepcopy(rule.keyword_ids),'brand':rule.brand,'name_core':rule.name_core})
    proposal['corrected_variant_id'] = variant_id
    proposal['corrected_specification'] = {key:package.get(key) for key in
        ('package_quantity','package_unit','bundle_count','display_unit')}
    proposal['corrected_quote'] = price_fields['price']
    new_event_id = 'offer-corrected-'+correction_key[:32]
    proposal['corrected_event_id'] = new_event_id
    bundle['offers'] = [{**_row(event),**price_fields,'public_offer_event_id':new_event_id,
        'standard_unit_price':rate,'price_per_100g':per100g,
        'raw_evidence':{**deepcopy(event.raw_evidence or {}),
            'promotion_conditions':deepcopy(price_fields['promotion_conditions'])},
        'audit_provenance':{'source_correction_lineage':proposal},
        'offer_state':'pending_review' if hold else (('active' if proved_base_role else event.offer_state) if not price_changed
            else ('pending_review' if price_issues else 'active'))}]
    validation = validate_bundle(session,bundle,_digest(bundle),source_correction_preview=True)
    if not validation.ok:
        raise HTTPException(422, {'message':'Existing formal bundle validation rejected correction',
                                  'validation':validation.as_dict()})
    projected_variant = bundle['variants'][0] if bundle['variants'] else _row(variant)
    projected_listing = bundle['source_listings'][0] if bundle['source_listings'] else _row(listing)
    proposal_hash = source_correction_proposal_hash(bundle['offers'][0],projected_variant,projected_listing)
    return {'has_changes':True,'prefill':prefill,'source_specification':package,
        'source_price':price_fields,'proposal_sha256':proposal_hash,'bundle':bundle,
        'quantity_scope_action':action,'quantity_scope_reasons':sorted(scope_issues),
        'source_specification_status':'unresolved_scope_historical_literal' if hold else 'source_supported',
        'new_variant_id':variant_id,'new_event_id':new_event_id,'validation':validation.as_dict(),
        'applied':False,'snapshot_published':False}


def apply_correction(session, product_id, selection, expected_hash, *, identity, request=None):
    """Official moderator apply; proposal inspection alone never approves it."""
    from services.audit import log_action
    from services.catalog_bundle import apply_bundle
    existing = session.scalar(select(NormalizedOfferEvent).where(
        NormalizedOfferEvent.public_source_listing_id == selection['public_source_listing_id'],
        NormalizedOfferEvent.audit_provenance['source_correction_lineage']['proposal_sha256'].as_string() == expected_hash))
    if existing is not None:
        lineage = existing.audit_provenance['source_correction_lineage']
        original = session.get(NormalizedOfferEvent,lineage.get('original_event_id'))
        if (lineage.get('status') != 'approved' or lineage.get('selection_sha256') != _digest(selection)
                or lineage.get('public_product_id') != product_id or original is None
                or lineage.get('original_event_sha256') != source_correction_event_hash(_row(original))):
            raise HTTPException(409,'Existing correction does not match this exact reviewed request')
        return {'applied':True,'idempotent':True,'new_event_id':existing.public_offer_event_id,
            'new_variant_id':lineage['corrected_variant_id'],'snapshot_published':False}
    preview = correction_preview(session,product_id,selection,identity=identity)
    if not preview['has_changes']:
        return {'applied':False,'has_changes':False,'snapshot_published':False}
    if preview['proposal_sha256'] != expected_hash:
        raise HTTPException(409,'Correction preview changed; inspect a new preview before applying')
    bundle = deepcopy(preview['bundle'])
    for row in [*bundle['variants'],*bundle['offers']]:
        layer = row.get('audit_provenance') if 'public_offer_event_id' in row else row.get('attributes')
        lineage = layer['source_correction_lineage']
        lineage.update(status='approved',proposal_sha256=expected_hash)
    result = apply_bundle(session,bundle,_digest(bundle),user=str(identity.get('sub') or identity.get('email') or 'moderator'))
    log_action(session,action='normalized_source_correction_apply',entity_type='normalized_offer_event',
        entity_id=preview['new_event_id'],old_value=preview['prefill'],
        new_value={'proposal_sha256':expected_hash,'new_event_id':preview['new_event_id'],
                   'new_variant_id':preview['new_variant_id']},request=request,
        user_id=str(identity.get('sub') or identity.get('email') or 'moderator'))
    return {'applied':True,'idempotent':result['idempotent'],'counts':result['applied'],
        'new_event_id':preview['new_event_id'],'new_variant_id':preview['new_variant_id'],
        'proposal_sha256':expected_hash,'snapshot_published':False}
