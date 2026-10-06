"""Exact additional source facts required by a manually reviewed listing.

Quote amounts never gate identity; original observed displays remain auditable.
Native category values and official URLs
are retained as supplied; they do not create loose product-name rules.
"""
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
import unicodedata
import re
import json
import math

PATH_FIELDS = ('mart_native_category_path', 'source_category_path', 'category_path', 'category', 'category_hint')


def source_review_evidence(payload):
    if not isinstance(payload, Mapping):
        return {'source_urls': [], 'source_fields': {}}
    attrs = payload.get('attributes') or payload.get('attrs') or {}
    attrs = attrs if isinstance(attrs, Mapping) else {}
    fields = {prefix + key: layer[key] for prefix, layer in (('', payload), ('attributes.', attrs))
              for key in PATH_FIELDS if layer.get(key) not in (None, '')}
    urls = sorted({unicodedata.normalize('NFKC', str(layer[key])).strip()
                   for layer in (payload, attrs) for key in ('canonical_url', 'detail_url', 'source_url')
                   if layer.get(key)})
    return {'source_urls': urls, 'source_fields': fields}


def source_review_matches(actual, required):
    if (not isinstance(required, Mapping) or not isinstance(required.get('source_urls'), list)
            or not required['source_urls'] or not all(isinstance(url, str) and url for url in required['source_urls'])):
        return False
    expected_fields = required.get('source_fields', {})
    return (isinstance(expected_fields, Mapping)
            and set(actual.get('source_urls', ())) == set(required['source_urls'])
            and all(key in actual.get('source_fields', {}) and actual['source_fields'][key] == value
                    for key, value in expected_fields.items()))


QUANTITY_FIELDS = ('package_quantity', 'pack_qty', 'packQty', 'pack_quantity', 'packQuantity',
                   'package_unit', 'pack_unit', 'packUnit', 'unitName', 'bundle_count', 'bundleCount',
                   'display_unit', 'unit')


def listing_quantity_evidence(payload, attrs=None):
    """Retain supplied capacity/specification fields without making them counts."""
    result = {}
    layers = [('', payload)]
    layers += [('attributes.', payload.get(key)) for key in ('attributes', 'attrs')]
    if attrs:
        layers.append(('attributes.', attrs))
    for prefix, layer in layers:
        if not isinstance(layer, Mapping):
            continue
        for key in QUANTITY_FIELDS:
            value = layer.get(key)
            if value in (None, ''):
                continue
            name = prefix + key
            if name in result and result[name] != value:
                raise ValueError('conflicting quantity layers')
            result[name] = value
        # Quote amounts can change. Their stated basis is compatibility evidence.
        for key in ('unit_price_display', 'unit_price_basis', 'unit_price_basis_raw',
                    'unit_price_text', 'unit_price_unit'):
            value = layer.get(key)
            if value in (None, ''):
                continue
            match = re.fullmatch(r'\s*(?:(\d+(?:\.\d+)?)\s*)?([a-zA-Z가-힣]+)\s*(?:당\s*([0-9,]+(?:\.[0-9]+)?)\s*원)?\s*',
                                 unicodedata.normalize('NFKC', str(value)))
            if not match or (match[3] and float(match[3].replace(',', '')) <= 0):
                raise ValueError('invalid quote basis')
            result[prefix + key] = [match[1], match[2].casefold()]
    return result


def _quoted_display_basis(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*([a-zA-Z가-힣]+)\s*당\s*((?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?)\s*원\s*',
                         unicodedata.normalize('NFKC', value))
    if not match:
        return None
    amount, price = Decimal(match[1]), Decimal(match[3].replace(',', ''))
    if not all(number.is_finite() and number > 0 for number in (amount, price)):
        return None
    return amount, match[2].casefold()


def quantity_evidence_matches(actual, expected):
    """Keep observed evidence immutable; quote money is never a quantity gate."""
    if not isinstance(actual, Mapping) or not isinstance(expected, Mapping) or set(actual) != set(expected):
        return False
    for key, value in actual.items():
        if value == expected[key]:
            continue
        # Some crawlers put complete monetary quotes into these display fields.
        # Both sides must still be quotes with the same positive quantity basis;
        # a bare measurement, changed unit/count or malformed input cannot match.
        if key.rsplit('.', 1)[-1] not in {'unit', 'display_unit'}:
            return False
        basis = _quoted_display_basis(value)
        if basis is None or basis != _quoted_display_basis(expected[key]):
            return False
    return True


def source_observation_eligibility_review(payload, attrs, title):
    """Separate a reviewed factual gap from an independently exact SKU context.

    An unmatched source receives no exception. A bound but changed quantity or
    quote basis remains rejected; monetary amounts never enter this evidence.
    """
    from core.reviewed_content_quantities import REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
    title = unicodedata.normalize('NFKC', str(title)).strip()
    choices = [record for record in REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
               if record['title'] == title
               and source_review_matches(source_review_evidence(payload), record['required_source'])]
    if not choices:
        return None
    try:
        quantity = listing_quantity_evidence(payload, attrs)
        matches = [record for record in choices if quantity_evidence_matches(quantity, record['quantity_fields'])]
    except (ValueError, TypeError, OverflowError):
        matches = []
    if len(matches) != 1:
        return None, ['source_observation_evidence_conflict']
    review = matches[0]
    if review['status'] == 'hold':
        return None, ['source_observation_factual_hold', review['hold_reason']]
    if review['status'] != 'eligible':
        return None, ['source_observation_evidence_conflict']
    return review, []


def _source_identity_context_proof(review):
    context = review.get('identity_context')
    if not isinstance(context, Mapping):
        return None
    if (not isinstance(context.get('partition_key'), str)
            or not context.get('source_name') or not context.get('source_record_key')
            or not isinstance(context.get('normalized'), list)
            or len(context['normalized']) != 3):
        return None
    return {'version': 1, **dict(context), 'title': review['title'],
            'category_id': review['category_id'], 'required_source': review['required_source'],
            'quantity_fields': review['quantity_fields']}


def source_identity_context_review(source_name, source_record_key, payload, title):
    """Select an explicitly reviewed identity context without transferring attributes.

    The empty partition retains its historical IDs. Separate contexts remain
    source bound, with their own exact title and sold quantity; money is absent.
    """
    if not isinstance(payload, Mapping):
        return None
    attrs = payload.get('attributes')
    attrs = attrs if isinstance(attrs, Mapping) else {}
    eligibility = source_observation_eligibility_review(payload, attrs, title)
    if not eligibility or eligibility[1] or eligibility[0] is None:
        return None
    proof = _source_identity_context_proof(eligibility[0])
    if (proof is None or proof['source_name'] != source_name
            or proof['source_record_key'] != source_record_key):
        return None
    return proof


def source_identity_context_for_variant(variant, listing):
    """Recognize an original anchor without modifying its historical attributes."""
    from core.reviewed_content_quantities import REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
    attrs = variant.get('attributes')
    if not isinstance(attrs, Mapping):
        return None
    proof = attrs.get('source_identity_context')
    if 'source_identity_context' in attrs:
        return proof if isinstance(proof, Mapping) else None
    matches = [_source_identity_context_proof(record)
               for record in REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
               if record.get('status') == 'eligible' and record.get('identity_context')
               and record['identity_context'].get('partition_key') == ''
               and record['identity_context'].get('source_name') == listing.get('source_name')
               and record['identity_context'].get('source_record_key') == listing.get('source_record_key')
               and record['title'] == unicodedata.normalize('NFKC', str(listing.get('source_title'))).strip()]
    return matches[0] if len(matches) == 1 else None


def valid_source_identity_context(variant, listing, category_id):
    """Only registered complete contexts permit repeated native SKUs in a bundle."""
    from core.reviewed_content_quantities import REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
    attrs = variant.get('attributes')
    proof = source_identity_context_for_variant(variant, listing)
    if not isinstance(attrs, Mapping) or proof is None:
        return False
    registered = [_source_identity_context_proof(record)
                  for record in REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
                  if record.get('status') == 'eligible']
    if proof not in registered or proof['category_id'] != category_id:
        return False
    if ([variant.get('package_quantity'), variant.get('package_unit'), variant.get('bundle_count')]
            != proof['normalized']):
        return False
    if any(listing.get(key) != proof[key] for key in ('source_name', 'source_record_key')):
        return False
    if unicodedata.normalize('NFKC', str(listing.get('source_title'))).strip() != proof['title']:
        return False
    if listing.get('source_url') not in proof['required_source']['source_urls']:
        return False
    required = {'source_name': proof['source_name'], 'source_record_key': proof['source_record_key'],
                **proof['required_source']}
    reviews = attrs.get('source_evidence_reviews')
    return isinstance(reviews, list) and required in reviews


def nonmeasured_listing_review(payload, attrs, title):
    from core.reviewed_content_quantities import REVIEWED_NONMEASURED_LISTINGS
    title = unicodedata.normalize('NFKC', str(title)).strip()
    choices = [record for record in REVIEWED_NONMEASURED_LISTINGS if record['title'] == title]
    if not choices:
        return None
    try:
        quantity = listing_quantity_evidence(payload, attrs)
    except (ValueError, TypeError, OverflowError):
        return None, ['nonmeasured_listing_evidence_conflict']
    matching = [record for record in choices
                if source_review_matches(source_review_evidence(payload), record['required_source'])
                and quantity_evidence_matches(quantity, record['quantity_fields'])]
    if len(matching) != 1:
        return None, ['nonmeasured_listing_evidence_conflict']
    review = matching[0]
    if (review.get('measurement_role') == 'declared_additive_battery_pack'
            and not _valid_additive_battery_pack_review(review, None)):
        return None, ['nonmeasured_listing_evidence_conflict']
    count = review.get('declared_package_bundle_count', 1)
    if type(count) is not int or count < 1:
        return None, ['nonmeasured_listing_evidence_conflict']
    if count > 1:
        labels = [layer.get('promo_label') for layer in (payload, payload.get('attributes'), attrs)
                  if isinstance(layer, Mapping) and layer.get('promo_label') not in (None, '')]
        if (count != 2 or review.get('required_promotion_label') != '1+1'
                or not labels or any(label != '1+1' for label in labels)):
            return None, ['nonmeasured_listing_evidence_conflict']
    basis = ('reviewed_purchased_packages_not_piece_count' if count > 1
             else 'one_source_listing_not_piece_count')
    return {'package_quantity': None, 'package_unit': None, 'bundle_count': count,
            'standard_unit': None, 'display_unit': '',
            'attributes': {'quantity_basis': 'nonmeasured_source_listing_v1',
                           'sold_piece_count': None,
                           'bundle_count_basis': basis,
                           'nonmeasured_listing': review}}, []


def valid_nonmeasured_variant(variant):
    from core.reviewed_content_quantities import REVIEWED_NONMEASURED_LISTINGS
    attrs = variant.get('attributes') or {}
    review = attrs.get('nonmeasured_listing') if isinstance(attrs, Mapping) else None
    count = review.get('declared_package_bundle_count', 1) if isinstance(review, Mapping) else None
    basis = ('reviewed_purchased_packages_not_piece_count' if type(count) is int and count > 1
             else 'one_source_listing_not_piece_count')
    return (isinstance(review, Mapping) and review in REVIEWED_NONMEASURED_LISTINGS
            and bool(review.get('title'))
            and isinstance(review.get('quantity_fields'), Mapping)
            and source_review_matches(review.get('required_source', {}), review.get('required_source', {}))
            and attrs.get('quantity_basis') == 'nonmeasured_source_listing_v1'
            and 'sold_piece_count' in attrs and attrs['sold_piece_count'] is None
            and type(count) is int and count >= 1
            and (count == 1 or count == 2 and review.get('required_promotion_label') == '1+1')
            and attrs.get('bundle_count_basis') == basis
            and variant.get('package_quantity') is None and variant.get('package_unit') is None
            and type(variant.get('bundle_count')) is int and variant.get('bundle_count') == count
            and variant.get('standard_unit') is None
            and not attrs.get('package_components')
            and (review.get('measurement_role') != 'declared_additive_battery_pack'
                 or _valid_additive_battery_pack_review(review, None)))


def _reviewed_source_attributes_match(payload, attrs, review):
    layers = (payload, payload.get('attributes'), payload.get('attrs'), attrs)
    for field, required in (('image_url', 'required_source_image_url'),
                            ('collection', 'required_source_collection')):
        expected = review.get(required)
        if expected is None:
            continue
        values = [layer[field] for layer in layers
                  if isinstance(layer, Mapping) and layer.get(field) not in (None, '')]
        if (not isinstance(expected, str) or not expected or not values
                or any(not isinstance(value, str) or value != expected for value in values)):
            return False
    return True


def explicit_listing_standard_unit(review):
    unit = review['normalized'][1]
    if unit in {'g', 'ml'}:
        return unit
    if unit == 'm' and review.get('measurement_role') == 'declared_linear_contents':
        return unit
    return None


def _explicit_quantity_matches(quantity, review):
    expected = review['quantity_fields']
    if review.get('measurement_role') in {'declared_outer_set_count', 'declared_nonexact_mass_specification', 'declared_incomplete_entitlement_specification', 'declared_incomplete_retail_package_specification'}:
        # Original quoted count rates are not inner food amounts or payment.
        # Keep their basis compatible without using the mutable money value.
        return quantity_evidence_matches(quantity, expected)
    if _scalar_comparison_hold(review):
        # A quote basis is compatibility evidence, not the sold measurement.
        # Retain exact supplied sales fields while allowing absent/changed
        # compatible rate bases on this independently measured package.
        unit = review['normalized'][1]
        compatible = {'g', 'kg'} if unit == 'g' else {'ml', 'l'} if unit == 'ml' else set()
        clean = []
        for fields in (quantity, expected):
            sales = {}
            for key, value in fields.items():
                if key.rsplit('.', 1)[-1] in {'unit_price_display', 'unit_price_basis',
                        'unit_price_basis_raw', 'unit_price_text', 'unit_price_unit'}:
                    amount, basis = value
                    if basis not in compatible or (amount is not None and
                            (not math.isfinite(float(amount)) or float(amount) <= 0)):
                        return False
                else:
                    sales[key] = value
            clean.append(sales)
        return quantity_evidence_matches(*clean)
    if review.get('measurement_role') != 'declared_linear_contents':
        return quantity_evidence_matches(quantity, expected)
    # New compatible length quotes describe a price basis, not another sold
    # quantity. Keep all source quantity fields exact and reject other bases.
    actual = dict(quantity)
    for key in tuple(actual):
        if key in expected:
            continue
        if key.rsplit('.', 1)[-1] not in {
                'unit_price_display', 'unit_price_basis', 'unit_price_basis_raw',
                'unit_price_text', 'unit_price_unit'}:
            continue
        amount, unit = actual[key]
        if unit != 'm' or (amount is not None and
                           (not math.isfinite(float(amount)) or float(amount) <= 0)):
            return False
        del actual[key]
    return quantity_evidence_matches(actual, expected)


def explicit_listing_package(payload, attrs, title):
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    title = unicodedata.normalize('NFKC', str(title)).strip()
    choices = [record for record in REVIEWED_EXPLICIT_LISTING_PACKAGES if record['title'] == title]
    if not choices:
        return None
    # A source-bound bulk review does not make an unbound wholesale title
    # eligible. Preserve the original diagnostic alongside the source conflict.
    conflict = ['reviewed_listing_quantity_conflict']
    if any(record.get('measurement_role') == 'declared_nonexact_mass_specification' for record in choices):
        conflict.append('approximate_measured_quantity_unresolved')
    if any(record.get('measurement_role') == 'declared_incomplete_retail_package_specification' for record in choices):
        conflict.append('bundle_multiplier_unresolved')
    for record in choices:
        if record.get('measurement_role') == 'declared_incomplete_entitlement_specification':
            reason = ('stored_value_certificate_sold_count_unresolved'
                      if record.get('category_id') == 'services.vouchers.cafe.monetary'
                      else 'unit_service_occupancy_not_entitlement')
            if reason not in conflict:
                conflict.append(reason)
    if any(isinstance(record.get('independent_specifications'), Mapping)
           and record['independent_specifications'].get('sale_scope')
           == 'declared_full_bulk_listing' for record in choices):
        conflict.append('bulk_package_review_required')
    try:
        quantity = listing_quantity_evidence(payload, attrs)
    except (ValueError, TypeError, OverflowError):
        return None, conflict
    matching = [record for record in choices
                if source_review_matches(source_review_evidence(payload), record['required_source'])
                and _explicit_quantity_matches(quantity, record)
                and _reviewed_source_attributes_match(payload, attrs, record)]
    if len(matching) != 1:
        return None, conflict
    review = matching[0]
    q, u, count = review['normalized']
    package = {'package_quantity':q, 'package_unit':u, 'bundle_count':count,
            'standard_unit':explicit_listing_standard_unit(review),
            'display_unit':review.get('preserved_display_unit',
                f'{q:g}{u}×{count}' if review.get('measurement_role') == 'declared_linear_contents' else title),
            'attributes':{'explicit_listing_quantity_review':review}}
    if review.get('preserved_specification_basis'):
        package['attributes']['specification_basis'] = review['preserved_specification_basis']
    # A fully declared sales hierarchy can be measured independently of an
    # incomplete assortment. Preserve the measurement without inventing its
    # recipes or permitting a fixed/comparable variant.
    hold = review.get('eligibility_hold_reason')
    if hold:
        package['attributes']['declared_package_structure'] = review['declared_package_structure']
    if review.get('measurement_role') in {'declared_unselected_entity_count', 'declared_exclusive_option_containers', 'declared_outer_set_count', 'declared_nonexact_mass_specification', 'declared_incomplete_entitlement_specification', 'declared_incomplete_retail_package_specification', 'declared_additive_battery_pack'} and not valid_explicit_listing_variant(package):
        return None, conflict
    return package, [hold] if hold else []


def valid_explicit_listing_variant(variant):
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    attrs = variant.get('attributes') or {}
    review = attrs.get('explicit_listing_quantity_review') if isinstance(attrs, Mapping) else None
    return (isinstance(review, Mapping) and review in REVIEWED_EXPLICIT_LISTING_PACKAGES
            and not review.get('eligibility_hold_reason')
            and [variant.get('package_quantity'),variant.get('package_unit'),variant.get('bundle_count')] == review['normalized']
            and variant.get('standard_unit') == explicit_listing_standard_unit(review)
            and not attrs.get('package_components')
            and (review.get('measurement_role') != 'declared_unselected_entity_count'
                 or (type(variant.get('bundle_count')) is int
                     and _valid_unselected_entity_count_review(review)
                     and _source_parent_selection_proof(review) is not None))
            and (review.get('measurement_role') != 'declared_exclusive_option_containers'
                 or source_selection_alternatives(variant) is not None)
            and (review.get('measurement_role') != 'declared_outer_set_count'
                 or _valid_outer_set_review(review))
            and (review.get('measurement_role') != 'declared_nonexact_mass_specification'
                 or (type(variant.get('bundle_count')) is int and _valid_nonexact_contents_review(review)))
            and (review.get('measurement_role') != 'declared_incomplete_entitlement_specification'
                 or (type(variant.get('bundle_count')) is int and _valid_entitlement_review(review)))
            and (review.get('measurement_role') != 'declared_incomplete_retail_package_specification'
                 or (type(variant.get('bundle_count')) is int and _valid_partial_retail_review(review)))
            and (review.get('measurement_role') != 'declared_additive_battery_pack'
                 or _valid_additive_battery_pack_review(review, review['normalized'])))


def _valid_additive_battery_pack_review(review, normalized):
    from core.catalog_quantity import additive_battery_pack_specification
    specification = additive_battery_pack_specification(review.get('title'), review.get('category_id'))
    if not specification or specification != review.get('declared_pack_specification'):
        return False
    expected = ([specification['total_count'], specification['count_unit'], 1]
                if specification['count_unit'] else None)
    return normalized == expected


def reviewed_additive_battery_pack(payload, attrs, title):
    """A badge does not independently establish buy/free purchase quantities."""
    for result in (explicit_listing_package(payload, attrs, title),
                   nonmeasured_listing_review(payload, attrs, title)):
        if result and result[0] and not result[1]:
            review = result[0]['attributes'].get('explicit_listing_quantity_review') or result[0]['attributes'].get('nonmeasured_listing')
            if review and review.get('measurement_role') == 'declared_additive_battery_pack':
                return review['declared_pack_specification']
    return None


def _valid_unselected_entity_count_review(review):
    """A literal whole-food count does not establish the selected recipe."""
    from core.catalog_quantity import _COUNT_UNIT_PATTERN, _COUNT_RANGE_RE
    spec = review.get('declared_sold_entity_count')
    if not isinstance(spec, Mapping) or set(spec) != {'value', 'original_unit', 'counted_entity', 'normalized_unit', 'literal'}:
        return False
    count = spec.get('value')
    title = unicodedata.normalize('NFKC', str(review.get('title') or ''))
    if (type(count) is not int or count <= 0
            or spec != {'value': count, 'original_unit': '판', 'counted_entity': 'whole_pizza',
                        'normalized_unit': '개', 'literal': f'{count}판'}
            or review.get('category_id') != 'food.meals.prepared.pizza'
            or review.get('normalized') != [count, '개', 1]
            or review.get('bundle_count_basis') != 'whole_declared_entity_count_normalized_once'
            or not isinstance(review.get('source_parent_selection'), Mapping)
            or review['source_parent_selection'].get('dimension') != 'recipe'
            or '피자' not in title or not re.search(r'골라\s*담기|선택|택일', title)
            or re.search(r'피자\s*(?:팬|틀|커터|칼)|팬|트레이|조각', title)):
        return False
    matches = list(re.finditer(r'(\d+)\s*판', title))
    if len(matches) != 1 or int(matches[0].group(1)) != count:
        return False
    residual = title[:matches[0].start()] + title[matches[0].end():]
    return not (re.search(r'\d+(?:[.,]\d+)?\s*(?:kg|g|ml|l|㎏|㎖|그램|리터)\b', residual, re.I)
                or re.search(r'\d+\s*(?:' + _COUNT_UNIT_PATTERN + r'|팩|봉|세트|종)', residual)
                or re.search(r'[×x*]\s*\d|\d+\s*[–~-]\s*\d+', residual, re.I)
                or _COUNT_RANGE_RE.search(residual))


def _valid_partial_retail_review(review):
    """A measured retail subpackage is not an established whole sale."""
    from core.reviewed_content_quantities import REVIEWED_LISTING_SPECIFICATIONS
    from core.catalog_quantity import _COUNT_UNIT_PATTERN, _COUNT_RANGE_RE
    spec = review.get('partial_retail_specification')
    proof = review.get('independent_specifications')
    hashes = proof.get('original_raw_payload_hashes') if isinstance(proof, Mapping) else None
    if (review.get('normalized') != [None, None, 1]
            or review.get('bundle_count_basis') != 'one_source_observation_not_sold_multiplier'
            or 'source_parent_selection' in review
            or not review.get('source_name') or not review.get('source_record_key')
            or not str(review.get('category_id') or '').startswith('food.')
            or review.get('comparison_hold_reason') != 'source_whole_sale_scope_unverified'
            or not isinstance(spec, Mapping) or not isinstance(hashes, Mapping) or not hashes
            or any(not isinstance(key, str) or not isinstance(value, str)
                   or not re.fullmatch(r'[0-9a-f]{64}', value) for key, value in hashes.items())):
        return False
    known = [record for record in REVIEWED_LISTING_SPECIFICATIONS
             if all(record.get(key) == review.get(key) for key in
                    ('title', 'category_id', 'source_name', 'source_record_key', 'required_source'))
             and record.get('source_evidence_sha256') == review.get('listing_specification_evidence_sha256')]
    attrs = known[0].get('classification_attributes') if len(known) == 1 else None
    if not isinstance(attrs, Mapping):
        return False
    value, unit, count = (attrs.get(key) for key in (
        'retail_package_net_contents_value', 'retail_package_net_contents_unit', 'retail_package_declared_count'))
    factor = attrs.get('unresolved_source_factor_literal')
    if (type(value) not in {int, float} or not math.isfinite(value) or value <= 0
            or unit not in {'g', 'kg', 'ml', 'l'} or type(count) is not int or count <= 0
            or attrs.get('retail_package_scope') != 'printed_retail_package_only'
            or attrs.get('retail_package_count_literal_unit') != '개입'
            or attrs.get('retail_package_counted_entity') is not None
            or attrs.get('sold_retail_package_count') is not None
            or not isinstance(factor, str) or not re.fullmatch(r'[1-9]\d*(?:\.\d+)?', factor)):
        return False
    expressions = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\s*/\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+)(?!\d)',
                             str(review.get('title') or ''), re.I)
    remainder = re.sub(r'(?<![\d.])\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\s*/\s*\d+(?:\.\d+)?\s*[x×]\s*\d+(?!\d)',
                       '', str(review.get('title') or ''), flags=re.I)
    if (_COUNT_RANGE_RE.search(remainder)
            or re.search(rf'(?<![\d.])\d+(?:\.\d+)?\s*(?:kg|g|ml|l|{_COUNT_UNIT_PATTERN})', remainder, re.I)
            or re.search(r'[x×]\s*\d', remainder, re.I)):
        return False
    return (len(expressions) == 1 and float(expressions[0][0]) == value
            and expressions[0][1].casefold() == unit and expressions[0][2] == factor
            and int(expressions[0][3]) == count
            and spec == {'kind': 'partial_retail_package', 'retail_package_scope': 'printed_retail_package_only',
                         'net_contents': {'value': value, 'unit': unit},
                         'declared_count': {'value': count, 'literal_unit': '개입', 'counted_entity': None},
                         'unresolved_source_factors': [{'literal': factor, 'unit': None, 'role': None}],
                         'sold_retail_package_count': None, 'whole_sold_contents': None})


def source_partial_retail_specification(variant):
    if not isinstance(variant, Mapping) or not valid_explicit_listing_variant(variant):
        return None
    review = variant['attributes']['explicit_listing_quantity_review']
    if review.get('measurement_role') == 'declared_incomplete_retail_package_specification':
        return review['partial_retail_specification']
    return None


def _valid_entitlement_review(review):
    """Known denomination or party wording does not establish sold rights."""
    from core.reviewed_content_quantities import REVIEWED_LISTING_SPECIFICATIONS
    spec = review.get('entitlement_specification')
    proof = review.get('independent_specifications')
    hashes = proof.get('original_raw_payload_hashes') if isinstance(proof, Mapping) else None
    if (review.get('normalized') != [None, None, 1]
            or review.get('bundle_count_basis') != 'one_source_observation_not_sold_multiplier'
            or 'source_parent_selection' in review
            or not review.get('source_name') or not review.get('source_record_key')
            or review.get('comparison_hold_reason') != 'source_entitlement_scope_unverified'
            or not isinstance(spec, Mapping)
            or not isinstance(hashes, Mapping) or not hashes
            or any(not isinstance(key, str) or not isinstance(value, str)
                   or not re.fullmatch(r'[0-9a-f]{64}', value) for key, value in hashes.items())):
        return False
    if spec.get('kind') == 'stored_value_voucher':
        known = [record for record in REVIEWED_LISTING_SPECIFICATIONS
                 if all(record.get(key) == review.get(key) for key in
                        ('title', 'category_id', 'source_name', 'source_record_key', 'required_source'))
                 and record.get('source_evidence_sha256') == review.get('listing_specification_evidence_sha256')]
        if len(known) != 1:
            return False
        attrs = known[0]['classification_attributes']
        if not isinstance(attrs, Mapping):
            return False
        return (spec == {'kind': 'stored_value_voucher', **{key: attrs[key] for key in (
                    'denomination_amount', 'denomination_currency', 'certificate_medium',
                    'sold_certificate_count', 'aggregate_entitlement_amount')}}
                and spec['sold_certificate_count'] is None and spec['aggregate_entitlement_amount'] is None
                and review.get('category_id') == 'services.vouchers.cafe.monetary'
                and not re.search(r'\d+\s*(?:매|장|개|세트|팩)', review['title']))
    if spec.get('kind') == 'facility_party_reference':
        literals = re.findall(r'(?<!\d)\d+\s*인\s*PKG', str(review.get('title') or ''), re.I)
        return (len(literals) == 1
                and spec == {'kind': 'facility_party_reference',
                             'party_reference_literal': re.sub(r'\s+', '', literals[0]),
                             'sold_entitlement_count': None, 'granted_person_count': None,
                             'maximum_capacity': None, 'duration': None}
                and review.get('category_id') == 'services.facility.camping.cabin_package'
                and not re.search(r'\d+\s*(?:박|일|매|개|장|회|티켓|인분)', review['title']))
    return False


def source_entitlement_specification(variant):
    if not isinstance(variant, Mapping) or not valid_explicit_listing_variant(variant):
        return None
    review = variant['attributes']['explicit_listing_quantity_review']
    if review.get('measurement_role') == 'declared_incomplete_entitlement_specification':
        return review['entitlement_specification']
    return None


def _valid_nonexact_contents_review(review):
    """Nominal and open-bound source specifications are never exact contents."""
    from core.catalog_quantity import _COUNT_UNIT_PATTERN, _COUNT_RANGE_RE
    spec = review.get('nonexact_contents_specification')
    proof = review.get('independent_specifications')
    hashes = proof.get('original_raw_payload_hashes') if isinstance(proof, Mapping) else None
    if (review.get('normalized') != [None, None, 1]
            or review.get('bundle_count_basis') != 'one_source_observation_not_sold_multiplier'
            or 'source_parent_selection' in review
            or not review.get('source_name') or not review.get('source_record_key')
            or not isinstance(spec, Mapping)
            or set(spec) != {'kind', 'value', 'unit', 'operator', 'reference_scope'}
            or spec.get('kind') not in {'approximate_nominal_mass', 'strict_upper_mass_bound'}
            or spec.get('operator') != ('approximately' if spec['kind'] == 'approximate_nominal_mass' else '<')
            or type(spec.get('value')) not in {int, float} or not math.isfinite(spec['value']) or spec['value'] <= 0
            or spec.get('unit') not in {'g', 'kg'}
            or spec.get('reference_scope') not in {'source_listing_unspecified_container', 'source_labelled_pack_reference'}
            or review.get('comparison_hold_reason') != 'source_exact_contents_unverified'
            or not isinstance(hashes, Mapping) or not hashes
            or any(not isinstance(key, str) or not isinstance(value, str)
                   or not re.fullmatch(r'[0-9a-f]{64}', value) for key, value in hashes.items())):
        return False
    estimates = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(kg|g)\s*(내외|미만)', str(review.get('title') or ''), re.I)
    title = str(review.get('title') or '')
    if (len(estimates) != 1 or _COUNT_RANGE_RE.search(title)
            or re.search(rf'(?<![\d.])\d+(?:\.\d+)?\s*(입팩|{_COUNT_UNIT_PATTERN})', title, re.I)
            or len(re.findall(r'(?<![\d.])\d+(?:\.\d+)?\s*(kg|g)', title, re.I)) != 1):
        return False
    value, unit, qualifier = estimates[0]
    return (float(value) == spec['value'] and unit.casefold() == spec['unit']
            and spec['operator'] == ('approximately' if qualifier == '내외' else '<')
            and spec['reference_scope'] == ('source_labelled_pack_reference'
                if re.search(r'/\s*팩', review['title']) else 'source_listing_unspecified_container'))


def source_nonexact_contents_specification(variant):
    if not isinstance(variant, Mapping) or not valid_explicit_listing_variant(variant):
        return None
    review = variant['attributes']['explicit_listing_quantity_review']
    if review.get('measurement_role') == 'declared_nonexact_mass_specification':
        return review['nonexact_contents_specification']
    return None


def _valid_outer_set_review(review):
    count = review.get('declared_outer_set_count')
    proof = review.get('independent_specifications')
    hashes = proof.get('original_raw_payload_hashes') if isinstance(proof, Mapping) else None
    return (type(count) is int and count > 0
            and review.get('normalized') == [count, '세트', 1]
            and review.get('inner_contents_resolved') is False
            and 'source_parent_selection' not in review
            and isinstance(hashes, Mapping) and bool(hashes)
            and all(isinstance(key, str) and isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                    for key, value in hashes.items())
            and _scalar_comparison_hold(review) == 'contents_identity_and_allocation_unverified')


def source_outer_set_count(variant):
    """Known total outer sets do not prove any inner food/companion amount."""
    if not isinstance(variant, Mapping) or not valid_explicit_listing_variant(variant):
        return None
    review = variant['attributes']['explicit_listing_quantity_review']
    if review.get('measurement_role') == 'declared_outer_set_count':
        return review['declared_outer_set_count']
    return None


def source_observational_raw_hashes(variant):
    """Initial typed incomplete observations retain exact original evidence."""
    if source_selection_alternatives(variant):
        return variant['attributes']['explicit_listing_quantity_review']['source_parent_selection']['original_raw_payload_hashes']
    if source_outer_set_count(variant) or source_nonexact_contents_specification(variant) or source_entitlement_specification(variant) or source_partial_retail_specification(variant):
        return variant['attributes']['explicit_listing_quantity_review']['independent_specifications']['original_raw_payload_hashes']
    return None


def source_selection_alternatives(variant):
    """Coupled source choices declare no common sold scalar or chosen branch.

    bundle_count=1 represents this one source observation, as with declared
    count intervals; it is never a sold-food singleton or multiplier.
    """
    from core.reviewed_content_quantities import REVIEWED_EXPLICIT_LISTING_PACKAGES
    if not isinstance(variant, Mapping):
        return None
    attrs = variant.get('attributes') or {}
    review = attrs.get('explicit_listing_quantity_review') if isinstance(attrs, Mapping) else None
    if (not isinstance(review, Mapping) or review not in REVIEWED_EXPLICIT_LISTING_PACKAGES
            or review.get('measurement_role') != 'declared_exclusive_option_containers'
            or review.get('bundle_count_basis') != 'one_source_observation_not_sold_multiplier'
            or review.get('normalized') != [None, None, 1]
            or _source_parent_selection_proof(review) is None
            or [variant.get('package_quantity'), variant.get('package_unit'), variant.get('bundle_count')]
               != [None, None, 1]
            or type(variant.get('bundle_count')) is not int
            or variant.get('standard_unit') is not None
            or attrs.get('package_components')):
        return None
    choices = review.get('source_exclusive_alternatives')
    if (not isinstance(choices, list) or len(choices) < 2
            or any(not isinstance(row, Mapping)
                   or set(row) != {'name', 'container_count', 'container_unit'}
                   or not isinstance(row['name'], str) or not row['name'].strip()
                   or type(row['container_count']) is not int or row['container_count'] <= 0
                   or row['container_unit'] not in {'봉', '팩', '세트', '개'} for row in choices)):
        return None
    signature = tuple(sorted((row['name'], row['container_count'], row['container_unit']) for row in choices))
    return signature if len({row[0] for row in signature}) == len(signature) else None


def _scalar_comparison_hold(review):
    """Validate separate known-quantity and unresolved-composition statements."""
    if review.get('component_allocation') is not None:
        return None
    reason = review.get('comparison_hold_reason')
    identities = review.get('content_identities')
    if reason == 'heterogeneous_contents_allocation_unverified':
        if (isinstance(identities, list) and all(isinstance(v, str) and v for v in identities)
                and len(set(identities)) >= 2):
            return reason
    if (reason == 'contents_identity_and_allocation_unverified'
            and identities is None and 'content_identities' in review
            and review.get('composition_scope') == 'source_listing_only'):
        return reason
    return None


def source_parent_selection(variant):
    """A reviewed selection surface is not a fixed, selected child SKU."""
    if not isinstance(variant, Mapping) or not valid_explicit_listing_variant(variant):
        return None
    review = variant['attributes']['explicit_listing_quantity_review']
    if review.get('normalized', [None])[0] is None and source_selection_alternatives(variant) is None:
        return None
    return _source_parent_selection_proof(review)


def _source_parent_selection_proof(review):
    if (review.get('measurement_role') == 'declared_unselected_entity_count'
            and not _valid_unselected_entity_count_review(review)):
        return None
    selection = review.get('source_parent_selection')
    if not isinstance(selection, Mapping):
        return None
    hashes = selection.get('original_raw_payload_hashes')
    if (selection.get('identity_scope') != 'source_selectable_parent_observation'
            or selection.get('selection_state') != 'not_declared_in_original'
            or not selection.get('dimension')
            or not isinstance(selection.get('original_selection_hold_reason'), str)
            or not selection['original_selection_hold_reason']
            or selection.get('selected_child_native_id') is not None
            or selection.get('selected_value') is not None
            or not review.get('source_name') or not review.get('source_record_key')
            or not isinstance(hashes, Mapping) or not hashes
            or any(not isinstance(key, str) or not isinstance(value, str)
                   or not re.fullmatch(r'[0-9a-f]{64}', value) for key, value in hashes.items())):
        return None
    return selection


def package_comparison_reason(variant):
    """Keep a known scalar aggregate apart from unproved recipe allocation.

    A comparison limit does not hold identity, quantity or the observation.
    Complete immutable source review still binds the scalar specification.
    """
    attrs = variant.get('attributes') or {}
    if not isinstance(attrs, Mapping):
        return 'quantity_evidence_unverified'
    if ('source_component_listing' in attrs
            or attrs.get('quantity_basis') == 'reviewed_source_component_vector_v1'):
        # A stored scalar or stale serialized contract must not make an
        # unverified contents vector look like an ordinary priced package.
        return None if valid_source_component_variant(variant) else 'quantity_evidence_unverified'
    if 'explicit_listing_quantity_review' not in attrs:
        return None
    if not valid_explicit_listing_variant(variant):
        return 'quantity_evidence_unverified'
    review = attrs['explicit_listing_quantity_review']
    if source_nonexact_contents_specification(variant):
        return 'source_exact_contents_unverified'
    if source_entitlement_specification(variant):
        return 'source_entitlement_scope_unverified'
    if source_partial_retail_specification(variant):
        return 'source_whole_sale_scope_unverified'
    if 'source_parent_selection' in review:
        return ('source_option_selection_unverified' if source_parent_selection(variant)
                else 'quantity_evidence_unverified')
    reason = review.get('comparison_hold_reason')
    if reason is None:
        return None
    if not _scalar_comparison_hold(review):
        return 'quantity_evidence_unverified'
    return reason


def original_quantity_assertion(variant):
    """A measured historical assertion does not resolve a later source conflict."""
    if not isinstance(variant, Mapping) or not valid_explicit_listing_variant(variant):
        return None
    review = variant['attributes']['explicit_listing_quantity_review']
    proof = review.get('original_quantity_assertion')
    if not isinstance(proof, Mapping) or not _scalar_comparison_hold(review):
        return None
    counts = proof.get('nested_sold_counts')
    hashes = proof.get('raw_payload_hashes')
    later = proof.get('later_conflicting_assertions')
    if (proof.get('scope') != 'original_observation_only'
            or not isinstance(counts, list) or len(counts) < 2
            or any(type(count) is not int or count <= 0 for count in counts)
            or [proof.get('per_item_quantity'), proof.get('unit'), math.prod(counts)] != review['normalized']
            or not isinstance(hashes, Mapping) or not hashes
            or any(not isinstance(key, str) or not isinstance(digest, str)
                   or not re.fullmatch(r'[0-9a-f]{64}', digest) for key, digest in hashes.items())
            or not isinstance(later, list) or len(later) < 2
            or any(not isinstance(row, Mapping) or not isinstance(row.get('assertion'), str)
                   or not isinstance(row.get('capture_sha256'), str)
                   or not re.fullmatch(r'[0-9a-f]{64}', row['capture_sha256']) for row in later)
            or proof.get('current_publication_hold') != 'later_source_quantity_conflict_unresolved'):
        return None
    return proof


def package_publication_reason(variant):
    if source_parent_selection(variant):
        return 'source_option_selection_unverified'
    if source_outer_set_count(variant):
        return 'source_outer_set_contents_unverified'
    if source_nonexact_contents_specification(variant):
        return 'source_exact_contents_unverified'
    if source_entitlement_specification(variant):
        return 'source_entitlement_scope_unverified'
    if source_partial_retail_specification(variant):
        return 'source_whole_sale_scope_unverified'
    proof = original_quantity_assertion(variant)
    return proof['current_publication_hold'] if proof else None


def frozen_raw_meat_category(category_id, title):
    """Storage refines the same raw species; it never changes sold contents."""
    if (category_id not in {'food.meat.fresh.beef', 'food.meat.fresh.pork', 'food.meat.fresh.chicken'}
            or not isinstance(title, str) or '냉동' not in title
            or re.search(r'냉동\s*(?:가능|보관용|고|실|보관\s*가능)', title)
            or re.search(r'양념|훈제|소시지|햄|불고기|볶음|덮밥|돈까스|만두|패티|스테이크|찌개|가공|조리|소스|혼합|장난감|반려|애견|강아지|고양이', title)):
        return None
    return category_id.replace('.fresh.', '.frozen.')


def explicit_listing_category_compatible(variant, category_id):
    """Keep exact historical quantity proof through same-species storage refinement.

    The original reviewed record, quantity and source identity remain mandatory.
    Other species, preparations, contents and quantity changes are incompatible.
    """
    if not isinstance(variant, Mapping) or not valid_explicit_listing_variant(variant):
        return False
    review = variant['attributes']['explicit_listing_quantity_review']
    return (category_id == review['category_id'] or category_id is not None
            and category_id == frozen_raw_meat_category(review['category_id'], review['title']))


def valid_linear_contents_variant(variant):
    if not isinstance(variant, Mapping) or not valid_explicit_listing_variant(variant):
        return False
    review = variant['attributes']['explicit_listing_quantity_review']
    return (review.get('measurement_role') == 'declared_linear_contents'
            and variant.get('package_unit') == 'm')


def count_interval_listing_package(payload, attrs, title):
    """A bounded count declaration is evidence, never an exact sold quantity."""
    from core.reviewed_content_quantities import REVIEWED_COUNT_INTERVAL_LISTINGS
    title = unicodedata.normalize('NFKC', str(title)).strip()
    choices = [record for record in REVIEWED_COUNT_INTERVAL_LISTINGS if record['title'] == title]
    if not choices:
        return None
    try:
        quantity = listing_quantity_evidence(payload, attrs)
        matches = [record for record in choices
                   if source_review_matches(source_review_evidence(payload), record['required_source'])
                   and quantity_evidence_matches(quantity, record['quantity_fields'])]
    except (ValueError, TypeError, OverflowError):
        matches = []
    if len(matches) != 1:
        return None, ['count_range_unresolved', 'reviewed_count_interval_evidence_conflict']
    review = matches[0]
    unit = review['count_interval'][2]
    return {'package_quantity': None, 'package_unit': unit, 'bundle_count': 1,
            'standard_unit': None, 'display_unit': title,
            'attributes': {'quantity_basis': 'reviewed_declared_count_interval_v1',
                           'sold_piece_count': None,
                           'bundle_count_basis': 'one_source_listing_not_piece_count',
                           'count_interval': list(review['count_interval']),
                           'count_interval_listing': review}}, []


def valid_count_interval_variant(variant):
    from core.reviewed_content_quantities import REVIEWED_COUNT_INTERVAL_LISTINGS
    attrs = variant.get('attributes') or {}
    review = attrs.get('count_interval_listing') if isinstance(attrs, Mapping) else None
    bounds = review.get('count_interval') if isinstance(review, Mapping) else None
    return (review in REVIEWED_COUNT_INTERVAL_LISTINGS and isinstance(bounds, list)
            and len(bounds) == 3 and all(type(value) is int for value in bounds[:2])
            and 0 < bounds[0] < bounds[1] and bounds[2] in {'개', '송이'}
            and (bounds[2] == '개' or review.get('identity_basis') == 'declared_interval_unit_v2')
            and attrs.get('quantity_basis') == 'reviewed_declared_count_interval_v1'
            and attrs.get('count_interval') == bounds
            and 'sold_piece_count' in attrs and attrs['sold_piece_count'] is None
            and attrs.get('bundle_count_basis') == 'one_source_listing_not_piece_count'
            and variant.get('package_quantity') is None and variant.get('package_unit') == bounds[2]
            and variant.get('bundle_count') == 1 and variant.get('standard_unit') is None
            and not attrs.get('package_components'))


def listing_title_history(source_name, source_key, payload, title):
    """Only explicitly reviewed same-SKU titles, with each original context kept."""
    from core.reviewed_content_quantities import REVIEWED_LISTING_TITLE_HISTORIES
    if not isinstance(payload, Mapping):
        return None
    title = unicodedata.normalize('NFKC', str(title)).strip()
    try:
        quantity = listing_quantity_evidence(payload)
    except (ValueError, TypeError, OverflowError):
        return None
    matches = [review for review in REVIEWED_LISTING_TITLE_HISTORIES
               if review['source_name'] == source_name and review['source_record_key'] == str(source_key)
               and any(alias['title'] == title
                       and source_review_matches(source_review_evidence(payload), alias['required_source'])
                       and quantity_evidence_matches(quantity, alias['quantity_fields']) for alias in review['aliases'])]
    return matches[0] if len(matches) == 1 else None


def valid_listing_title_history(review):
    from core.reviewed_content_quantities import REVIEWED_LISTING_TITLE_HISTORIES
    return isinstance(review, Mapping) and review in REVIEWED_LISTING_TITLE_HISTORIES


def source_component_signature(components):
    """Exact NULL-aware multiset; component totals do not invent piece counts."""
    if not isinstance(components, list) or len(components) < 2:
        raise ValueError('complete component vector required')
    result = []
    for row in components:
        if not isinstance(row, Mapping) or set(row) != {'identity','presentation','quantity','unit','count','amount_scope'}:
            raise ValueError('invalid component fields')
        if not isinstance(row['identity'], str) or not row['identity'].strip():
            raise ValueError('unknown component identity')
        q, u, count, scope = (row[key] for key in ('quantity','unit','count','amount_scope'))
        if count is not None and (type(count) is not int or count <= 0):
            raise ValueError('invalid sold count')
        if q is None:
            counted = scope == 'declared_sold_count' and count is not None
            physical = (scope == 'declared_nonmeasured_physical' and count is None
                        and isinstance(row['presentation'], str)
                        and row['presentation'] in {'basket', 'mug', 'dripper', 'server',
                                                    'timer', 'measuring_spoon',
                                                    'chimney_starter', 'drip_assist',
                                                    'feeding_bottle', 'gift_wrap', 'glass', 'shopping_bag'})
            # A reviewed physical companion may lack a sold piece count. Its
            # NULLs remain local to that component; consumable contents still
            # require a declared amount or an independently declared count.
            if u is not None or not (counted or physical):
                raise ValueError('unresolved content amount')
        elif (isinstance(q, bool) or not isinstance(q, (int,float)) or not 0 < q < float('inf')
                or u not in {'g','ml'} or scope not in {'declared_component_total','per_counted_component'}
                or (scope == 'declared_component_total') != (count is None)):
            raise ValueError('component amount scope conflict')
        if row['presentation'] is not None and not isinstance(row['presentation'], str):
            raise ValueError('invalid component presentation')
        result.append(tuple(row[key] for key in ('identity','presentation','quantity','unit','count','amount_scope')))
    return tuple(sorted(result, key=lambda row: json.dumps(row, ensure_ascii=False)))


def _component_quantity_matches(quantity, review):
    if review.get('measurement_role') not in {
            'measured_food_with_nonmeasured_physical_companion',
            'heterogeneous_declared_component_contents'}:
        return quantity_evidence_matches(quantity, review['quantity_fields'])
    # A compatible quote basis describes the food, not the complete gift's
    # identity. An absent quote does not remove independently declared contents.
    dimensions = {c['unit'] for c in review['components'] if c['quantity'] is not None}
    if len(dimensions) != 1:
        return False
    unit = next(iter(dimensions))
    allowed = {'g', 'kg'} if unit == 'g' else {'ml', 'l'}
    actual, expected = dict(quantity), dict(review['quantity_fields'])
    for values in (actual, expected):
        for key in tuple(values):
            if key.rsplit('.', 1)[-1] in {
                    'unit_price_display', 'unit_price_basis', 'unit_price_basis_raw',
                    'unit_price_text', 'unit_price_unit'}:
                amount, basis = values.pop(key)
                if basis not in allowed or (amount is not None and
                        (not math.isfinite(float(amount)) or float(amount) <= 0)):
                    return False
    return quantity_evidence_matches(actual, expected)


def source_component_listing_package(payload, attrs, title):
    from core.reviewed_content_quantities import REVIEWED_SOURCE_COMPONENT_LISTINGS
    title = unicodedata.normalize('NFKC', str(title)).strip()
    choices = [review for review in REVIEWED_SOURCE_COMPONENT_LISTINGS if review['title'] == title]
    if not choices:
        return None
    try:
        quantity = listing_quantity_evidence(payload, attrs)
        matching = [review for review in choices
                    if source_review_matches(source_review_evidence(payload), review['required_source'])
                    and _component_quantity_matches(quantity, review)]
        if len(matching) != 1:
            raise ValueError('source binding differs')
        review = matching[0]
        if not _reviewed_source_attributes_match(payload, attrs, review):
            raise ValueError('reviewed package attribute binding differs')
        signature = source_component_signature(review['components'])
        for layer in (payload, payload.get('attributes'), payload.get('attrs'), attrs):
            if not isinstance(layer, Mapping):
                continue
            if 'package_components' in layer:
                raise ValueError('homogeneous contract cannot replace mixed vector')
            if 'source_components' in layer and source_component_signature(layer['source_components']) != signature:
                raise ValueError('changed component vector')
    except (ValueError, TypeError, OverflowError):
        return None, ['mixed_package_unresolved', 'source_component_listing_evidence_conflict']
    return {'package_quantity':1, 'package_unit':'세트', 'bundle_count':1, 'standard_unit':None,
            'display_unit':title,
            'attributes': {'quantity_basis':'reviewed_source_component_vector_v1',
                           'scalar_basis':'one_complete_declared_vector_not_piece_count',
                           'source_components':review['components'], 'source_component_listing':review}}, \
            [review['eligibility_hold_reason']] if review.get('eligibility_hold_reason') else []


def valid_source_component_variant(variant):
    from core.reviewed_content_quantities import REVIEWED_SOURCE_COMPONENT_LISTINGS
    attrs = variant.get('attributes') or {}
    review = attrs.get('source_component_listing') if isinstance(attrs, Mapping) else None
    if not isinstance(review, Mapping) or review not in REVIEWED_SOURCE_COMPONENT_LISTINGS:
        return False
    try:
        return (not review.get('eligibility_hold_reason')
                and source_component_signature(attrs.get('source_components')) == source_component_signature(review['components'])
                and attrs.get('quantity_basis') == 'reviewed_source_component_vector_v1'
                and attrs.get('scalar_basis') == 'one_complete_declared_vector_not_piece_count'
                and variant.get('package_quantity') == 1 and variant.get('package_unit') == '세트'
                and variant.get('bundle_count') == 1 and variant.get('standard_unit') is None
                and 'package_components' not in attrs)
    except (ValueError, TypeError, OverflowError):
        return False


def reviewed_listing_specification(payload, title, category_id):
    """Source-bound partial facts never manufacture a package or an offer."""
    from core.reviewed_content_quantities import REVIEWED_LISTING_SPECIFICATIONS
    if not isinstance(payload, Mapping):
        return {}
    title = unicodedata.normalize('NFKC', str(title)).strip()
    layers = [payload, *[payload[key] for key in ('attributes', 'attrs') if isinstance(payload.get(key), Mapping)]]
    matches = []
    for review in REVIEWED_LISTING_SPECIFICATIONS:
        if title != review['title'] or category_id != review['category_id']:
            continue
        if not source_review_matches(source_review_evidence(payload), review['required_source']):
            continue
        keys = [str(layer[key]) for layer in layers for key in ('source_record_key', 'mart_native_code', 'cocodalin_join_key')
                if layer.get(key) not in (None, '')]
        sources = [str(layer[key]).casefold() for layer in layers for key in ('source', 'source_name', 'mart')
                   if layer.get(key) not in (None, '')]
        if not keys or any(key != review['source_record_key'] for key in keys):
            continue
        if not sources or any(source != review['source_name'] for source in sources):
            continue
        matches.append(review)
    return deepcopy(matches[0]['classification_attributes']) if len(matches) == 1 else {}
