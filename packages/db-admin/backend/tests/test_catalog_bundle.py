from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from services.catalog_bundle import SCHEMA_VERSION, apply_bundle, parse_bundle, validate_bundle
from storage.models import (
    Base,
    Keyword,
    MatchingEntry,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedProductVariant,
    NormalizedSourceListing,
    UnifiedCategory,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _bundle():
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "run-2026-08-30",
        "categories": [
            {"id": "food", "parent_id": None, "name_ko": "식품"},
            {"id": "food.dairy", "parent_id": "food", "name_ko": "유제품"},
            {"id": "food.dairy.milk", "parent_id": "food.dairy", "name_ko": "우유"},
            {"id": "food.dairy.milk.chocolate", "parent_id": "food.dairy.milk", "name_ko": "초코우유"},
        ],
        "keywords": [{
            "word": "초코우유",
            "synonyms": ["초콜릿우유", "chocolate milk"],
            "unified_category_id": "food.dairy.milk.chocolate",
        }],
        "products": [{
            "public_product_id": "prod-chocoemong",
            "unified_category_id": "food.dairy.milk.chocolate",
            "canonical_name": "초코에몽",
            "classification_confidence": 0.95,
        }],
        "variants": [{
            "public_variant_id": "var-chocoemong-120ml-24",
            "public_product_id": "prod-chocoemong",
            "variant_name": "초코에몽 120ml 24개",
            "package_quantity": 120,
            "package_unit": "ml",
            "bundle_count": 24,
        }],
        "source_listings": [{
            "public_source_listing_id": "listing-emart-1",
            "public_variant_id": "var-chocoemong-120ml-24",
            "source_name": "emart",
            "source_record_key": "1",
            "source_title": "초코에몽 120ml*24",
            "source_url": "https://example.test/1",
        }],
        "offers": [{
            "public_offer_event_id": "offer-emart-1-20260830",
            "public_source_listing_id": "listing-emart-1",
            "price_state": "normal",
            "promotion_type": "was_now_price",
            "price": 19900,
            "original_price": 24000,
            "crawled_at": "2026-08-30T00:00:00Z",
        }],
        "week_buckets": [{
            "public_week_bucket_id": "week-20260824",
            "week_start": "2026-08-24T00:00:00Z",
            "week_end": "2026-08-31T00:00:00Z",
        }],
        "offer_week_links": [{
            "public_offer_event_id": "offer-emart-1-20260830",
            "public_week_bucket_id": "week-20260824",
            "observed_min_price": 19900,
            "observed_max_price": 19900,
        }],
        "match_rules": [{
            "match_key": "남양|초코에몽|120.000000|ml",
            "public_product_id": "prod-chocoemong",
            "public_variant_id": "var-chocoemong-120ml-24",
            "confidence": 0.98,
        }],
        "mart_category_mappings": [{
            "mart": "emart",
            "mart_native_id": "dairy/milk/choco",
            "mart_native_path": "유제품 > 우유 > 초코우유",
            "unified_category_id": "food.dairy.milk.chocolate",
            "trust": "external-ai",
            "confidence": 0.95,
        }],
        "unresolved": [],
    }


def _offer_review_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _physical_role_bundle(category, title, quantity, unit):
    from core.catalog_quantity import normalize_catalog_package
    bundle = _bundle()
    source = {'name': title, 'detail_url': 'https://example.test/physical',
              'pack_qty': quantity, 'pack_unit': unit}
    package, issues = normalize_catalog_package(source, {}, title, category_id=category)
    assert package and not issues
    bundle['categories'] = [{'id': category, 'parent_id': None, 'name_ko': '물리 규격 검수'}]
    bundle['products'][0].update(unified_category_id=category, canonical_name=title)
    bundle['variants'][0].update(package, variant_name=title)
    bundle['source_listings'][0].update(source_title=title, source_url=source['detail_url'], source_unit_text=title)
    bundle['offers'][0].update(promotion_type='final_price', price=10000, original_price=None,
        offer_state='active', raw_evidence={'observations':[{'raw_record_id':'synthetic-physical:0',
            'raw_payload':source,'raw_payload_sha256':_offer_review_digest(source)}]})
    for key in ('keywords','match_rules','mart_category_mappings','week_buckets','offer_week_links'):
        bundle[key] = []
    return bundle


@pytest.mark.parametrize('category,title,quantity,unit,count,count_unit', [
    ('household.security.storage.safe','금고 40L',40000,'ml',None,None),
    ('household.outdoor.bags.cooler_tote','쿨러백 16L',16000,'ml',None,None),
    ('household.bath.textiles.towel','타월 150g 1P',150,'g',1,'개'),
    ('household.bath.textiles.towel','타월 130g 5P',130,'g',5,'개'),
    ('stationery.office.paper.copy','A4 복사지 80g 500매',80,'g',500,'매'),
    ('stationery.office.paper.copy','A4 복사지 80g 2500매',80,'g',2500,'매'),
    ('office.equipment.shredder.standard','문서세단기 19L',19000,'ml',None,None),
])
def test_physical_role_official_import_retains_spec_and_only_declared_count(category,title,quantity,unit,count,count_unit):
    session = _session()
    bundle = _physical_role_bundle(category,title,quantity,unit)
    variant = bundle['variants'][0]
    assert (variant['package_quantity'],variant['package_unit']) == (count,count_unit)
    assert variant['standard_unit'] is None
    result = apply_bundle(session,bundle,'physical-role',user='synthetic-reviewer')
    assert result['ok'] and not result['idempotent']
    stored = session.get(NormalizedProductVariant,variant['public_variant_id'])
    assert (stored.package_quantity,stored.package_unit) == (count,count_unit)
    assert stored.attributes['physical_device_specification']['quantity_fields']['pack_qty'] == quantity
    # Monetary observation changes cannot invalidate the same source/spec role.
    changed = deepcopy(bundle)
    changed['offers'][0].update(public_offer_event_id='offer-physical-new-price',price=11000)
    assert validate_bundle(session,changed,'physical-new-price').ok
    apply_bundle(session,changed,'physical-new-price',user='synthetic-reviewer')
    assert session.get(NormalizedOfferEvent,'offer-physical-new-price').price == 11000
    assert session.get(NormalizedOfferEvent,bundle['offers'][0]['public_offer_event_id']).price == 10000
    assert stored.attributes == variant['attributes']
    session.close()


@pytest.mark.parametrize('boundary',['source_url','source_title','sold_count','coordinated_sold_count','count_unit','basis','category','malformed_proof','paper_null'])
def test_physical_role_import_rejects_unbound_or_forged_purpose(boundary):
    bundle = _physical_role_bundle('stationery.office.paper.copy','A4 복사지 80g 500매',80,'g')
    variant = bundle['variants'][0]
    if boundary == 'source_url': bundle['source_listings'][0]['source_url'] = 'https://example.test/different'
    if boundary == 'source_title': bundle['source_listings'][0]['source_title'] = 'A4 복사지 80g 2500매'
    if boundary == 'sold_count': variant['package_quantity'] = 2500
    if boundary == 'coordinated_sold_count':
        variant['package_quantity'] = 2500
        variant['attributes']['physical_device_specification']['sold_piece_count'] = 2500
    if boundary == 'count_unit':
        variant['package_unit'] = '개'
        variant['attributes']['physical_device_specification']['sold_count_unit'] = '개'
    if boundary == 'basis': variant['standard_unit'] = 'g'
    if boundary == 'category':
        bundle['products'][0]['unified_category_id'] = 'household.bath.textiles.towel'
        bundle['categories'][0]['id'] = 'household.bath.textiles.towel'
    if boundary == 'malformed_proof': variant['attributes']['physical_device_specification'] = 'not-an-object'
    if boundary == 'paper_null':
        variant.update(package_quantity=None,package_unit=None)
        variant['attributes']['physical_device_specification']['sold_piece_count'] = None
    session = _session()
    assert not validate_bundle(session,bundle,'physical-forgery').ok
    session.close()


def _offer_review_fixture(family="minimum_order2_without_discount", event_name=None):
    bundle = _bundle()
    bundle["products"][0]["is_active"] = False
    variant = bundle["variants"][0]
    variant.update(standard_unit="ml", display_unit="120ml × 24", attributes={})
    listing = bundle["source_listings"][0]
    if family == "minimum_order2_without_discount":
        listing.update(source_name="costco", source_record_key="615852",
                       source_title="초코에몽 120ml*24 / 최소구매 2",
                       source_url="https://www.costco.co.kr/Foods/Milk/p/615852")
        event, terms = None, {"source_title_purchase_condition": listing["source_title"]}
    elif family == "observed_source_quote_purchase_conditions_unverified":
        listing.update(source_name="homeplus", source_record_key="059102628",
                       source_url="https://mfront.homeplus.co.kr/item?itemNo=059102628&storeType=HYPER")
        event = None
        facts = {"source_condition_kind": "source_quote_purchase_conditions_unverified",
                 "payable_price_unconfirmed": True, "minimum_purchase_quantity_unconfirmed": True,
                 "coupon_application_unconfirmed": True}
        terms = {"promotion_conditions": facts}
    else:
        listing.update(source_name="lottemart", source_record_key="8809797610001",
                       source_url="https://lottemartzetta.com/products/OS8809797610001/details")
        event = {"conditional_selection_observation": event_name or "3개씩 골라 담으면, 그 중 1개는 무료",
                 "conditional_program_observation": event_name or "농할 할인 20%_결제시 자동적용",
                 "conditional_basket_spend_observation": event_name or "[동서식품] 4.5만↑ 5천원 할인"}.get(
                    family, "산란일자가 7/31~8/6 인 상품입니다.")
        terms = {}
    raw = {"name": listing["source_title"], "source_url": listing["source_url"],
           "price": 19900, "sale_price": 19900, "original_price": None,
           "event_name": event, "attributes": {}}
    if family == "observed_source_quote_purchase_conditions_unverified":
        source = {"basic": {"itemNo": listing["source_record_key"], "itemNm": listing["source_title"],
                             "storeType": "HYPER"}, "sale": {"salePrice": 19900, "dcPrice": 0}}
        raw["attributes"] = {"homeplus_detail_source_fields": source,
                             "homeplus_detail_source_fields_sha256": _offer_review_digest(source),
                             "promotion_conditions": facts}
    observation = {"raw_record_id": "ingestion:10:0", "raw_payload": raw,
                   "raw_payload_sha256": _offer_review_digest(raw)}
    offer = bundle["offers"][0]
    offer.update(price_state="sale_price_only", promotion_type="unknown", original_price=None,
                 offer_state="pending_review", event_name=event, raw_record_id="ingestion:10:0",
                 raw_evidence={"observations": [observation], "promotion_conditions": terms},
                 audit_provenance={"review_reasons": ["unknown_promotion"]})
    return bundle


def _offer_review_payload(original, family="minimum_order2_without_discount", source_quote_terms=None):
    reviewed = deepcopy(original)
    offer, listing, variant, product = (reviewed[key][0] for key in
                                        ("offers", "source_listings", "variants", "products"))
    terms = deepcopy(offer["raw_evidence"]["promotion_conditions"])
    if family == "minimum_order2_without_discount":
        terms.update(minimum_quantity=2, condition_text="최소구매 2")
    elif family == "conditional_selection_observation":
        from core.promotion_semantics import conditional_selection_facts_or_none
        terms = conditional_selection_facts_or_none(offer["event_name"]) or {}
    elif family == "conditional_program_observation":
        from core.promotion_semantics import conditional_program_facts_or_none
        terms = conditional_program_facts_or_none(offer["event_name"]) or {}
    elif family == "conditional_basket_spend_observation":
        from core.promotion_semantics import conditional_basket_spend_facts_or_none
        terms = conditional_basket_spend_facts_or_none(offer["event_name"]) or {}
    elif family == "observed_source_quote_purchase_conditions_unverified":
        terms = deepcopy(terms["promotion_conditions"])
    elif family == 'native_source_quote_purchase_conditions_unverified':
        terms = deepcopy(source_quote_terms)
    # Missing eligibility is unknown. A source review must never supply False.
    terms.update(membership_required=None, coupon_required=None)
    quote = {key: offer.get(key) for key in ("price", "original_price", "price_state", "event_name",
                                            "valid_from", "valid_to", "crawled_at")}
    binding = {"public_offer_event_id": offer["public_offer_event_id"],
               "public_source_listing_id": listing["public_source_listing_id"],
               "public_variant_id": variant["public_variant_id"],
               "public_product_id": product["public_product_id"],
               "unified_category_id": product["unified_category_id"],
               **{key: listing[key] for key in ("source_name", "source_record_key", "source_title", "source_url")},
               "variant_spec": {**{key: variant.get(key) for key in
                    ("variant_name", "display_unit", "package_quantity", "package_unit", "bundle_count", "standard_unit")},
                    "attributes_sha256": _offer_review_digest(variant["attributes"])},
               "quote": quote,
               "observations": [{"raw_record_id": row["raw_record_id"],
                    "raw_payload_sha256": row["raw_payload_sha256"],
                    "observation_sha256": _offer_review_digest(row)}
                    for row in offer["raw_evidence"]["observations"]]}
    offer["audit_provenance"]["offer_interpretation_review"] = {
        "version": 1, "status": "approved", "approved_by": "synthetic-moderator",
        "approved_at": "2026-10-04T00:00:00Z", "family": family, "binding": binding,
        "before": {"promotion_type": "unknown", "offer_state": "pending_review",
                   "promotion_conditions": deepcopy(offer["raw_evidence"]["promotion_conditions"])},
        "interpretation": {"promotion_type": "unknown" if family in {"conditional_selection_observation", "conditional_program_observation", "conditional_basket_spend_observation", "observed_source_quote_purchase_conditions_unverified", "native_source_quote_purchase_conditions_unverified"} else "final_price", "offer_state": "active",
                           "promotion_conditions": terms}}
    return reviewed


def _native_quote_fixture(source, normal_producer_marker=False):
    original = _offer_review_fixture('observed_source_quote_purchase_conditions_unverified')
    listing, variant, offer = (original[key][0] for key in ('source_listings', 'variants', 'offers'))
    marker = {'source_condition_kind': 'source_quote_purchase_conditions_unverified',
              'payable_price_unconfirmed': True}
    terms = {'coupon_application_unconfirmed': True, 'currency_unconfirmed': False}
    attrs = {'source_name': source}
    if source == 'homeplus':
        native, title, price, quantity, unit, bundles = ('059102628', 'simplus 무라벨 맑은샘물 2.0L*6', 2190, 2000, 'ml', 6)
        url = f'https://mfront.homeplus.co.kr/item?itemNo={native}&storeType=HYPER'
        limit = {'purchaseLimitYn': 'Y', 'purchaseLimitDuration': 'O', 'purchaseLimitDay': 0,
                 'purchaseLimitQty': 2, 'itemPurchaseLimitMessage': '최대 2개 구매가능', 'cartLimitYn': 'N'}
        coupons = [{'displayCouponNm': '장바구니 쿠폰', 'manageCouponNm': label, 'storeType': 'HYPER',
                    'purchaseMin': threshold, 'discount': discount, 'discountType': '2', 'discountMax': 0,
                    'issueStartDt': '2026-10-01 00:00:00', 'issueEndDt': '2026-10-07 23:59:59'}
                   for label, threshold, discount in [('[컨틴] 7만/4천 10.01~07', 70000, 4000),
                                                      ('[컨틴] 5만/2천 10.01~07', 50000, 2000)]]
        node = {'basic': {'itemNo': native, 'itemNm': title, 'storeType': 'HYPER'},
                'sale': {'salePrice': price, 'dcPrice': 0, 'purchaseMinQty': 1, **limit, 'eventList': []},
                'notice': [{'noticeNm': '포장단위별 내용물의 용량(중량), 수량', 'noticeDesc': '2L * 6입'}],
                'promo': {'couponInfo': deepcopy(coupons[0]), 'couponList': deepcopy(coupons)}}
        attrs.update(homeplus_detail_source_fields=node, homeplus_detail_source_fields_sha256=_offer_review_digest(node))
        marker.update(coupon_application_unconfirmed=True, minimum_purchase_quantity_unconfirmed=False,
                      source_minimum_purchase_quantity=1, source_maximum_purchase_quantity=2, source_quote_currency=None)
        terms.update(currency_unconfirmed=True, source_purchase_limit=limit,
                     source_coupon_declarations={'couponInfo': deepcopy(coupons[0]), 'couponList': coupons})
        event, display = None, '2L×6'
    elif source == 'costco':
        native, title, price, quantity, unit, bundles = ('649298', '벨미오 캡슐커피 클래식 80개입', 40990, 80, '개', 1)
        short = f'https://www.costco.co.kr/Foods/CoffeeTeaDrink/p/{native}'
        url = f'https://www.costco.co.kr/Foods/CoffeeTeaDrink/Capsule-Coffee/Belmio-Classic-Coffee-Capsules-80ea/p/{native}'
        price_node = {'currencyIso': 'KRW', 'value': float(price), 'intValue': price}
        node = {'code': native, 'name': title, 'url': url.split('costco.co.kr')[1], 'price': deepcopy(price_node),
                'basePrice': deepcopy(price_node), 'minOrderQuantity': 1, 'maxOrderQuantity': 500,
                'couponDiscount': {'discountType': 'default', 'hideDiscountCalculation': False}}
        missing = ['maxOrderQuantityMode', 'maxOrderQuantityPerDateRange', 'membership',
                   'membershipRestrictionApplied', 'modulusItemQuantity']
        attrs['submission_business_evidence'] = [{'raw_product_node': node,
                                                   'original_product_field_names': [*node, *missing]}]
        variant['attributes'] = {'source_evidence_reviews': [
            {'source_name': source, 'source_record_key': native, 'source_urls': [value], 'source_fields': {}}
            for value in (short, url)]}
        marker.update(membership_eligibility_unconfirmed=True, source_minimum_purchase_quantity=1,
                      source_maximum_order_quantity=500, source_quote_currency='KRW',
                      source_public_flag_values_unrecoverable=True)
        terms.update(source_unrecoverable_public_fields=sorted(missing), source_coupon_declaration=deepcopy(node['couponDiscount']))
        event, display = None, '80개입'
    else:
        native, title, price, quantity, unit, bundles = ('0000049320367', '크라시에 시즈쿠 유자 샤베트 (140ML)', 3900, 140, 'ml', 1)
        url = f'https://lottemartzetta.com/products/OS{native}/details'
        event, display = '3개씩 골라 담으면, 그 중 1개는 무료', '140ml'
        node = {'retailerProductId': 'OS' + native, 'name': title, 'packSizeDescription': display,
                'price': {'amount': str(price), 'currency': 'KRW'},
                'promotions': [{'description': event, 'requiredProductQuantity': 3}]}
        attrs.update(lottemart_detail_source_fields=node, lottemart_detail_source_fields_sha256=_offer_review_digest(node))
        marker.update(selected_product_scope_unconfirmed=True, source_required_product_quantity=3,
                      source_free_quantity=1, source_quote_currency='KRW')
        terms['condition_text'] = event
    listing.update(source_name=source, source_record_key=native, source_title=title,
                   source_url=short if source == 'costco' else url)
    variant.update(variant_name=title, package_quantity=quantity, package_unit=unit, bundle_count=bundles,
                   display_unit=display, standard_unit=unit if unit == 'ml' else None)
    original_marker = ({'source_condition_kind': 'source_quote_purchase_conditions_unverified',
                        'payable_price_unconfirmed': True,
                        'minimum_purchase_quantity_unconfirmed': True,
                        'coupon_application_unconfirmed': True}
                       if normal_producer_marker else marker)
    attrs.update(source_record_key=native, source_url=url, promotion_conditions=original_marker)
    raw = {'source': source, 'name': title, 'source_title': title, 'source_record_key': native,
           'source_url': url, 'sale_price': price, 'original_price': None, 'event_name': event,
           'package_quantity': quantity, 'package_unit': unit, 'attributes': attrs}
    attrs['bundle_count'] = bundles
    observation = offer['raw_evidence']['observations'][0]
    observation.update(raw_payload=raw, raw_payload_sha256=_offer_review_digest(raw))
    offer.update(price=price, event_name=event, raw_evidence={'observations': [observation],
                 'promotion_conditions': {'promotion_conditions': original_marker}})
    return original, {**marker, **terms}


@pytest.mark.parametrize('source,normal_producer_marker', [
    ('homeplus', False), ('costco', False), ('lottemart', False), ('homeplus', True)])
def test_native_quote_review_preserves_source_conditions_quote_history_and_sticky_replay(source, normal_producer_marker):
    family = 'native_source_quote_purchase_conditions_unverified'
    original, terms = _native_quote_fixture(source, normal_producer_marker)
    reviewed = _offer_review_payload(original, family, source_quote_terms=terms)
    session = _session()
    replay = {**deepcopy(original), 'run_id': 'new-original-replay'}
    for index, bundle in enumerate((original, reviewed, replay, reviewed)):
        raw = json.dumps(bundle, ensure_ascii=False).encode()
        parsed, digest = parse_bundle(raw, 'native-quote.json')
        validation = validate_bundle(session, parsed, digest)
        assert validation.ok, validation.errors
        result = apply_bundle(session, parsed, digest, user='synthetic-moderator')
        assert result['idempotent'] is (index == 3)
    identity = original['offers'][0]['public_offer_event_id']
    stored = session.get(NormalizedOfferEvent, identity)
    assert stored.offer_state == 'active' and stored.promotion_type == 'unknown'
    assert stored.price == original['offers'][0]['price']
    assert stored.standard_unit_price is None and stored.price_per_100g is None
    assert stored.discount_rate is None
    assert stored.raw_evidence['observations'] == original['offers'][0]['raw_evidence']['observations']
    assert stored.raw_evidence['promotion_conditions'] == {**terms, 'membership_required': None, 'coupon_required': None}
    assert 'minimum_quantity' not in stored.raw_evidence['promotion_conditions']
    assert session.get(NormalizedCanonicalProduct, original['products'][0]['public_product_id']).is_active
    # A valid changed quote is a NEW event, not a price-dependent identity change.
    changed = deepcopy(original)
    new = changed['offers'][0]
    new.update(public_offer_event_id='new-quote-event', price=new['price'] + 100)
    observation = new['raw_evidence']['observations'][0]
    raw = observation['raw_payload'];raw['sale_price'] = new['price']
    if source == 'homeplus':
        node = raw['attributes']['homeplus_detail_source_fields'];node['sale']['salePrice'] = new['price']
        raw['attributes']['homeplus_detail_source_fields_sha256'] = _offer_review_digest(node)
    elif source == 'lottemart':
        node = raw['attributes']['lottemart_detail_source_fields'];node['price']['amount'] = str(new['price'])
        raw['attributes']['lottemart_detail_source_fields_sha256'] = _offer_review_digest(node)
    else:
        node = raw['attributes']['submission_business_evidence'][0]['raw_product_node']
        for key in ('price', 'basePrice'):node[key].update(value=float(new['price']), intValue=new['price'])
    observation['raw_record_id'] = 'new-raw-event';observation['raw_payload_sha256'] = _offer_review_digest(raw)
    assert validate_bundle(session, changed, 'new-quote').ok
    apply_bundle(session, changed, 'new-quote', user='synthetic-moderator')
    later = session.get(NormalizedOfferEvent, 'new-quote-event')
    assert later.price == new['price'] and later.offer_state == 'pending_review'
    assert 'offer_interpretation_review' not in later.audit_provenance
    assert stored.price == original['offers'][0]['price']
    assert stored.audit_provenance['offer_interpretation_review'] == reviewed['offers'][0]['audit_provenance']['offer_interpretation_review']
    session.close()


@pytest.mark.parametrize('source,change', [
    ('homeplus', 'source_quote'), ('homeplus', 'source_native'), ('homeplus', 'source_store'),
    ('homeplus', 'minimum_bool'), ('homeplus', 'maximum_float'), ('homeplus', 'coupon_money'),
    ('homeplus', 'quantity_notice'), ('homeplus', 'source_hash'),
    ('costco', 'unregistered_url'), ('costco', 'ambiguous_context'), ('costco', 'source_quote'),
    ('costco', 'source_native'), ('costco', 'currency'), ('costco', 'maximum_float'),
    ('lottemart', 'source_quote'), ('lottemart', 'source_native'), ('lottemart', 'currency'),
    ('lottemart', 'selection_float'), ('lottemart', 'selection_conflict'), ('lottemart', 'source_package'),
    ('lottemart', 'source_hash'), ('lottemart', 'extra_eligibility'), ('homeplus', 'terms_bool'),
    ('costco', 'terms_float'), ('lottemart', 'historical_quote'), ('homeplus', 'raw_quantity'),
    ('costco', 'raw_quote_alias'), ('costco', 'attribute_quote_alias'),
    ('lottemart', 'supplemental_quote'), ('homeplus', 'sibling_native'), ('homeplus', 'option_selection'),
    ('homeplus', 'legacy_family'), ('costco', 'wrong_host'), ('lottemart', 'wrong_url_native'),
    ('homeplus', 'producer_source_hash'), ('homeplus', 'producer_option_selection'),
    ('homeplus', 'producer_raw_quantity'), ('homeplus', 'producer_coupon_money'),
    ('homeplus', 'producer_marker_forgery')])
def test_native_quote_review_rejects_source_context_types_or_payment_forgery(source, change):
    family = 'native_source_quote_purchase_conditions_unverified'
    normal_producer_marker = change.startswith('producer_')
    change = change.removeprefix('producer_')
    original, terms = _native_quote_fixture(source, normal_producer_marker)
    raw = original['offers'][0]['raw_evidence']['observations'][0]['raw_payload'];attrs = raw['attributes']
    node = (attrs.get('homeplus_detail_source_fields') or attrs.get('lottemart_detail_source_fields')
            or attrs.get('submission_business_evidence', [{}])[0].get('raw_product_node'))
    if change == 'source_quote':
        if source == 'homeplus':node['sale']['salePrice'] = 999
        elif source == 'lottemart':node['price']['amount'] = '999'
        else:node['price']['value'] = 999
    elif change == 'source_native' and source == 'homeplus':
        node['basic']['itemNo'] = 'other'
    elif change == 'source_store':node['basic']['storeType'] = 'EXP'
    elif change == 'minimum_bool':node['sale']['purchaseMinQty'] = True
    elif change == 'maximum_float':
        if source == 'homeplus':node['sale']['purchaseLimitQty'] = 2.0
        else:node['maxOrderQuantity'] = 500.0
    elif change == 'coupon_money':node['promo']['couponList'][0]['discount'] = True
    elif change == 'quantity_notice':node['notice'][0]['noticeDesc'] = '2L * 12입'
    elif change == 'currency':node['price']['currency' if source == 'lottemart' else 'currencyIso'] = 'USD'
    elif change == 'selection_float':node['promotions'][0]['requiredProductQuantity'] = 3.0
    elif change == 'selection_conflict':node['promotions'][0]['requiredProductQuantity'] = 2
    elif change == 'source_package':node['packSizeDescription'] = '280ml'
    elif change == 'unregistered_url':original['variants'][0]['attributes']['source_evidence_reviews'].pop()
    elif change == 'ambiguous_context':
        original['variants'][0]['attributes']['source_evidence_reviews'].append(
            deepcopy(original['variants'][0]['attributes']['source_evidence_reviews'][-1]))
    elif change == 'raw_quantity':raw['package_quantity'] = 3000
    elif change == 'marker_forgery':attrs['promotion_conditions']['payable_price_unconfirmed'] = False
    elif change == 'wrong_host':
        raw['source_url'] = attrs['source_url'] = raw['source_url'].replace('www.costco.co.kr', 'wrong.example')
    elif change == 'wrong_url_native':
        raw['source_url'] = attrs['source_url'] = raw['source_url'].replace('OS0000049320367', 'OSother')
    elif change == 'raw_quote_alias':raw['price'] = 999
    elif change == 'attribute_quote_alias':attrs['price'] = 999
    elif change == 'sibling_native':node['sale']['itemNo'] = 'other'
    elif change == 'option_selection':node['opt'] = {'optSelUseYn': 'Y'}
    elif change == 'supplemental_quote':
        attrs['submission_business_evidence'] = [{'raw_product_node': {
            'sku': node['retailerProductId'], 'name': node['name'], 'size': node['packSizeDescription'],
            'offers': {'price': '999', 'priceCurrency': 'KRW'}}}]
    if change == 'source_native' and source != 'homeplus':
        node['code' if source == 'costco' else 'retailerProductId'] = 'other'
    for namespace in ('homeplus', 'lottemart'):
        if f'{namespace}_detail_source_fields' in attrs:
            attrs[f'{namespace}_detail_source_fields_sha256'] = _offer_review_digest(node)
    if change == 'source_hash':attrs[f'{source}_detail_source_fields_sha256'] = 'wrong'
    observation = original['offers'][0]['raw_evidence']['observations'][0]
    observation['raw_payload_sha256'] = _offer_review_digest(raw)
    reviewed = _offer_review_payload(original, family, source_quote_terms=terms)
    if change == 'legacy_family':
        reviewed = _offer_review_payload(original, 'observed_source_quote_purchase_conditions_unverified')
    after = reviewed['offers'][0]['audit_provenance']['offer_interpretation_review']['interpretation']['promotion_conditions']
    if change == 'extra_eligibility':after['coupon_required'] = False
    if change == 'terms_bool':after['source_minimum_purchase_quantity'] = True
    if change == 'terms_float':after['source_maximum_order_quantity'] = 500.0
    if change == 'historical_quote':reviewed['offers'][0]['price'] += 100
    session = _session()
    apply_bundle(session, original, 'native-original', user='synthetic-importer')
    validation = validate_bundle(session, reviewed, 'native-forged-review')
    assert not validation.ok
    assert any('offer_interpretation_review' in error for error in validation.errors), validation.errors
    session.close()


@pytest.mark.parametrize("raw_event", [None, ""])
def test_observed_partial_quote_review_replay_retains_unknown_payment_and_original_observation(raw_event):
    family = "observed_source_quote_purchase_conditions_unverified"
    original = _offer_review_fixture(family=family)
    observation = original["offers"][0]["raw_evidence"]["observations"][0]
    observation["raw_payload"]["event_name"] = raw_event
    observation["raw_payload_sha256"] = _offer_review_digest(observation["raw_payload"])
    reviewed = _offer_review_payload(original, family=family)
    session = _session()
    for bundle in (original, reviewed, original):
        raw = json.dumps(bundle, ensure_ascii=False).encode()
        parsed, digest = parse_bundle(raw, "quote.json")
        assert validate_bundle(session, parsed, digest).ok
        apply_bundle(session, parsed, digest, user="moderator")
    offer = session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"])
    assert offer.price == 19900 and offer.promotion_type == "unknown" and offer.offer_state == "active"
    assert offer.standard_unit_price is None and offer.price_per_100g is None
    assert offer.raw_evidence["promotion_conditions"]["payable_price_unconfirmed"] is True
    assert offer.raw_evidence["observations"] == original["offers"][0]["raw_evidence"]["observations"]


def _homeplus_basket_observation(selection=3, maximum=99):
    original = _offer_review_fixture('observed_source_quote_purchase_conditions_unverified')
    event = f'{selection}개 담으면, 9,990원에 구매 (최대 {maximum}개까지 행사/할인 적용)'
    offer = original['offers'][0]
    offer['event_name'] = event
    observation = offer['raw_evidence']['observations'][0]
    raw = observation['raw_payload']
    raw['event_name'] = event
    attrs = raw['attributes']
    source = attrs['homeplus_detail_source_fields']
    limit = {'purchaseLimitYn': 'Y', 'purchaseLimitDuration': 'P', 'purchaseLimitDay': 1,
             'purchaseLimitQty': 10, 'itemPurchaseLimitMessage': '1일 동안 최대 10개 구매가능'}
    tiers = [{'thresholdQty': selection, 'changeAmount': 9990, 'changePercent': None, 'thresholdAmount': None},
             {'thresholdQty': maximum, 'changeAmount': 123450, 'changePercent': None, 'thresholdAmount': None}]
    source['sale'].update(purchaseMinQty=1, **limit, eventList=[{
        'dispEventLabel': event, 'eventKind': 'INTERVAL', 'changeType': '2',
        'eventBenefitQty': selection, 'changeAmount': 9990, 'buyItemCnt': 5,
        'thresholdIntervals': tiers, 'eventStartDt': '2026-10-01', 'eventEndDt': '2026-10-14'}])
    attrs['homeplus_detail_source_fields_sha256'] = _offer_review_digest(source)
    observation['raw_payload_sha256'] = _offer_review_digest(raw)
    reviewed = _offer_review_payload(original, 'conditional_selection_observation')
    terms = reviewed['offers'][0]['audit_provenance']['offer_interpretation_review']['interpretation']['promotion_conditions']
    terms.update(source_order_minimum_quantity=1, source_purchase_limit=limit,
                 source_event_period={'start_date': '2026-10-01', 'end_date': '2026-10-14'},
                 source_selection_price_intervals=tiers, coupon_application_unconfirmed=True)
    return original, reviewed


@pytest.mark.parametrize('mutation', [None, 'unreviewed_title', 'wrong_native', 'wrong_quantity', 'wrong_url'])
def test_homeplus_condition_review_reuses_only_source_bound_registered_title_history(mutation):
    from core.reviewed_content_quantities import REVIEWED_LISTING_TITLE_HISTORIES
    from services.initial_taxonomy import taxonomy_categories
    history = next(row for row in REVIEWED_LISTING_TITLE_HISTORIES
                   if row['source_name'] == 'homeplus' and row['source_record_key'] == '070894758')
    original, _ = _homeplus_basket_observation()
    original['categories'] = taxonomy_categories({history['category_id']})
    original['keywords'] = []
    original['mart_category_mappings'] = []
    original['match_rules'] = []
    original['products'][0].update(unified_category_id=history['category_id'], canonical_name=history['aliases'][0]['title'])
    original['variants'][0].update(package_quantity=1, package_unit='개', bundle_count=1, standard_unit=None)
    listing = original['source_listings'][0]
    listing.update(source_record_key=history['source_record_key'], source_title=history['aliases'][0]['title'],
                   source_url=history['aliases'][0]['required_source']['source_urls'][0])
    raw = original['offers'][0]['raw_evidence']['observations'][0]['raw_payload']
    raw.update(name=history['aliases'][1]['title'], source_url=listing['source_url'])
    for key, value in history['aliases'][1]['required_source']['source_fields'].items():
        layer, field = (raw['attributes'], key[11:]) if key.startswith('attributes.') else (raw, key)
        layer[field] = value
    raw.update(history['aliases'][1]['quantity_fields'])
    source = raw['attributes']['homeplus_detail_source_fields']
    source['basic'].update(itemNo=history['source_record_key'], itemNm=raw['name'])
    if mutation == 'unreviewed_title':
        raw['name'] = source['basic']['itemNm'] = raw['name'].replace(' 200g', '  200g')
    elif mutation == 'wrong_native':
        listing['source_record_key'] += '-other'
    elif mutation == 'wrong_quantity':
        raw['package_quantity'] = 201
    elif mutation == 'wrong_url':
        raw['source_url'] += '-other'
    raw['attributes']['homeplus_detail_source_fields_sha256'] = _offer_review_digest(source)
    observation = original['offers'][0]['raw_evidence']['observations'][0]
    observation['raw_payload_sha256'] = _offer_review_digest(raw)
    session = _session()
    apply_bundle(session, original, 'title-history-original', user='tester')
    reviewed = _offer_review_payload(original, 'conditional_selection_observation')
    old_review = reviewed['offers'][0]['audit_provenance']['offer_interpretation_review']
    _, usual = _homeplus_basket_observation()
    old_review['interpretation']['promotion_conditions'] = usual['offers'][0]['audit_provenance']['offer_interpretation_review']['interpretation']['promotion_conditions']
    result = validate_bundle(session, reviewed, 'title-history-review')
    assert result.ok == (mutation is None), result.errors
    if mutation is None:
        apply_bundle(session, reviewed, 'title-history-review', user='tester')
        current = session.get(NormalizedOfferEvent, original['offers'][0]['public_offer_event_id'])
        assert current.raw_evidence['observations'] == original['offers'][0]['raw_evidence']['observations']
        assert current.price == 19900 and current.standard_unit_price is None
        assert session.get(NormalizedSourceListing, listing['public_source_listing_id']).source_title == listing['source_title']


def test_product_bundle_serialization_and_reimport_preserve_classification_and_keyword_arrays():
    from services.catalog_bundle import product_bundle_row
    session = _session()
    original = _bundle()
    original['products'][0].update(classification_confidence=0.79, review_status='approved',
                                  aliases=['원래 이름'], keywords=['초코'], attributes={'source_proof':'preserved'})
    apply_bundle(session, original, 'metadata-original', user='tester')
    current = session.get(NormalizedCanonicalProduct, original['products'][0]['public_product_id'])
    before = deepcopy(current.attributes)
    exported = json.loads(json.dumps(product_bundle_row(current)))
    assert exported['aliases'] == ['원래 이름'] and exported['keywords'] == ['초코', '초코우유']
    assert exported['classification_confidence'] == 0.79 and exported['review_status'] == 'approved'
    # Normalized model JSON stores these fields in attributes. Both official
    # serialization and that persisted representation retain the same review.
    del exported['classification_confidence'], exported['review_status']
    incoming = deepcopy(original)
    incoming['products'] = [exported]
    assert validate_bundle(session, incoming, 'metadata-roundtrip').ok
    apply_bundle(session, incoming, 'metadata-roundtrip', user='tester')
    assert current.attributes == before and current.keywords == ['초코', '초코우유'] and current.aliases == ['원래 이름']
    for field in ('keywords', 'aliases'):
        bad = deepcopy(incoming)
        bad['products'][0][field] = json.dumps(exported[field])
        assert not validate_bundle(session, bad, 'sql-json-string').ok
    bad = deepcopy(incoming)
    bad['products'][0]['attributes']['review_status'] = 'classified'
    assert not validate_bundle(session, bad, 'embedded-low-confidence-without-approval').ok


@pytest.mark.parametrize('selection,maximum', [(3, 99), (4, 100)])
def test_native_homeplus_condition_review_replay_preserves_quote_and_separate_quantity_roles(selection, maximum):
    from core.promotion_semantics import comparable_transaction_or_none
    original, reviewed = _homeplus_basket_observation(selection, maximum)
    session = _session()
    apply_bundle(session, original, 'homeplus-original', user='tester')
    apply_bundle(session, reviewed, 'homeplus-source-review', user='synthetic-moderator')
    session.commit()
    assert apply_bundle(session, reviewed, 'homeplus-source-review', user='tester')['idempotent']
    apply_bundle(session, original, 'homeplus-source-repacked', user='tester')
    session.commit()
    event = session.get(NormalizedOfferEvent, original['offers'][0]['public_offer_event_id'])
    assert event.offer_state == 'active' and event.promotion_type == 'unknown' and event.price == 19900
    assert event.raw_evidence['observations'] == original['offers'][0]['raw_evidence']['observations']
    terms = event.raw_evidence['promotion_conditions']
    assert terms['required_selection_quantity'] == selection and terms['conditional_basket_total_won'] == 9990
    assert terms['source_event_maximum_quantity'] == maximum
    assert terms['source_order_minimum_quantity'] == 1 and terms['source_purchase_limit']['purchaseLimitQty'] == 10
    assert len(terms['source_selection_price_intervals']) == 2  # No invented intermediate prices.
    assert 'minimum_quantity' not in terms and 'buy_quantity' not in terms and 'free_quantity' not in terms
    assert event.standard_unit_price is None and event.price_per_100g is None
    assert comparable_transaction_or_none(current_price=event.price, promotion_type=event.promotion_type,
                                          promotion_conditions=terms) is None
    assert event.audit_provenance['offer_interpretation_review'] == reviewed['offers'][0]['audit_provenance']['offer_interpretation_review']
    changed = deepcopy(original)
    raw = changed['offers'][0]['raw_evidence']['observations'][0]['raw_payload']
    raw['sale_price'] = raw['price'] = 21000
    changed['offers'][0]['price'] = 21000
    changed['offers'][0]['raw_evidence']['observations'][0]['raw_payload_sha256'] = _offer_review_digest(raw)
    assert not validate_bundle(session, changed, 'changed-price-same-old-event').ok
    session.close()


@pytest.mark.parametrize('change', ['maximum', 'received_count', 'daily_limit', 'event_node', 'source_hash'])
def test_homeplus_conditional_review_rejects_guessed_basket_or_changed_original_facts(change):
    original, reviewed = _homeplus_basket_observation()
    terms = reviewed['offers'][0]['audit_provenance']['offer_interpretation_review']['interpretation']['promotion_conditions']
    if change == 'maximum': terms['source_event_maximum_quantity'] = 100
    if change == 'received_count': terms['received_package_count'] = 3
    if change == 'daily_limit': terms['source_purchase_limit']['purchaseLimitQty'] = 99
    if change in {'event_node', 'source_hash'}:
        raw = original['offers'][0]['raw_evidence']['observations'][0]['raw_payload']
        attrs = raw['attributes']
        if change == 'event_node': attrs['homeplus_detail_source_fields']['sale']['eventList'][0]['eventBenefitQty'] = 5
        else: attrs['homeplus_detail_source_fields_sha256'] = '0' * 64
        original['offers'][0]['raw_evidence']['observations'][0]['raw_payload_sha256'] = _offer_review_digest(raw)
        # Rebind the review to the actual changed source: its semantic conflict still rejects.
        rebound = _offer_review_payload(original, 'conditional_selection_observation')
        reviewed['offers'][0]['audit_provenance']['offer_interpretation_review']['binding'] = rebound['offers'][0]['audit_provenance']['offer_interpretation_review']['binding']
    session = _session()
    apply_bundle(session, original, 'source-original', user='tester')
    assert not validate_bundle(session, reviewed, 'unsupported-interpretation').ok
    session.close()


@pytest.mark.parametrize("change", ["payment", "minimum", "native", "source_quote", "source_hash", "source_annotation"])
def test_observed_partial_quote_review_rejects_guessed_payment_and_changed_source(change):
    family = "observed_source_quote_purchase_conditions_unverified"
    original = _offer_review_fixture(family=family)
    if change not in {"payment", "minimum"}:
        observation = original["offers"][0]["raw_evidence"]["observations"][0]
        payload = observation["raw_payload"]
        attrs = payload["attributes"]
        if change == "native":
            attrs["homeplus_detail_source_fields"]["basic"]["itemNo"] = "999999999"
        elif change == "source_quote":
            attrs["homeplus_detail_source_fields"]["sale"]["salePrice"] = 19800
        elif change == "source_annotation":
            payload["event_name"] = "1+1"
        else:
            attrs["homeplus_detail_source_fields_sha256"] = "0" * 64
        if change != "source_hash":
            attrs["homeplus_detail_source_fields_sha256"] = _offer_review_digest(attrs["homeplus_detail_source_fields"])
        observation["raw_payload_sha256"] = _offer_review_digest(payload)
    reviewed = _offer_review_payload(original, family=family)
    if change in {"payment", "minimum"}:
        terms = reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]["interpretation"]["promotion_conditions"]
        terms["payable_price_unconfirmed" if change == "payment" else "minimum_quantity"] = False if change == "payment" else 1
    session = _session()
    parsed, digest = parse_bundle(json.dumps(original).encode(), "original.json")
    apply_bundle(session, parsed, digest, user="moderator")
    parsed, digest = parse_bundle(json.dumps(reviewed).encode(), "review.json")
    assert not validate_bundle(session, parsed, digest).ok


@pytest.mark.parametrize("event", ["[동서식품] 4.5만↑ 5천원 할인",
    "[동원] 4만원 이상 구매시, 5천원 즉시할인", "[행사카드] 명절세트 30만↑ 12% 할인",
    "제타패스 X 요즘 1만원 이상 3천원 할인"])
def test_basket_spend_review_replay_preserves_quote_and_unknown_payment(event):
    session = _session()
    family = "conditional_basket_spend_observation"
    original = _offer_review_fixture(family, event)
    apply_bundle(session, original, "spend-original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    apply_bundle(session, reviewed, "spend-reviewed", user="tester")
    session.commit()
    assert apply_bundle(session, reviewed, "spend-reviewed", user="tester")["idempotent"]
    apply_bundle(session, original, "spend-original-repacked", user="tester")
    session.commit()
    offer = session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"])
    assert offer.price == 19900 and offer.event_name == event and offer.offer_state == "active"
    assert offer.promotion_type == "unknown" and offer.discount_rate is None
    assert offer.standard_unit_price is None and offer.price_per_100g is None
    assert offer.raw_evidence["observations"] == original["offers"][0]["raw_evidence"]["observations"]
    assert offer.audit_provenance["offer_interpretation_review"] == reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]
    terms = offer.raw_evidence["promotion_conditions"]
    assert terms["condition_text"] == event and terms["payable_price_unconfirmed"] is True
    assert terms["source_threshold_inclusive"] is (True if "이상" in event else None)
    from core.promotion_semantics import comparable_transaction_or_none
    assert comparable_transaction_or_none(current_price=offer.price, promotion_type=offer.promotion_type,
                                          promotion_conditions=terms) is None
    assert session.query(NormalizedOfferEvent).count() == 1


@pytest.mark.parametrize("change", ["equality", "member", "float_threshold", "integer_flag",
                                   "wrong_spec", "wrong_url", "raw_quote"])
def test_basket_spend_review_rejects_changed_binding_or_inferred_qualification(change):
    session = _session()
    family = "conditional_basket_spend_observation"
    original = _offer_review_fixture(family)
    apply_bundle(session, original, "spend-original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    terms = reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]["interpretation"]["promotion_conditions"]
    if change == "equality": terms["source_threshold_inclusive"] = True
    elif change == "member": terms["membership_required"] = False
    elif change == "float_threshold": terms["source_spend_threshold_won"] = 45000.0
    elif change == "integer_flag": terms["payable_price_unconfirmed"] = 1
    elif change == "wrong_spec": reviewed["variants"][0]["package_quantity"] = 240
    elif change == "wrong_url": reviewed["source_listings"][0]["source_url"] += "-other"
    elif change == "raw_quote":
        raw = reviewed["offers"][0]["raw_evidence"]["observations"][0]
        raw["raw_payload"]["sale_price"] = 20900
        raw["raw_payload_sha256"] = _offer_review_digest(raw["raw_payload"])
    with pytest.raises(ValueError):
        apply_bundle(session, reviewed, "spend-rejected", user="tester")
    session.rollback()
    old = session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"])
    assert old.offer_state == "pending_review" and old.price == 19900


@pytest.mark.parametrize("family", ["minimum_order2_without_discount", "informationalannotations"])
def test_offer_interpretation_review_official_replay_preserves_history_and_visibility(family):
    session = _session()
    original = _offer_review_fixture(family)
    # Another known product remains hidden while its source interpretation
    # is still pending. Approving one offer is not a catalog-wide activation.
    for key, identity in (("products", "public_product_id"), ("variants", "public_variant_id"),
                          ("source_listings", "public_source_listing_id"), ("offers", "public_offer_event_id")):
        other = deepcopy(original[key][0])
        other[identity] += "-pending"
        for reference in ("public_product_id", "public_variant_id", "public_source_listing_id"):
            if reference in other and reference != identity:
                other[reference] += "-pending"
        if key == "source_listings":
            other["source_record_key"] += "-pending"
        original[key].append(other)
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    result = apply_bundle(session, reviewed, "reviewed", user="synthetic-moderator")
    session.commit()
    assert not result["idempotent"]
    assert apply_bundle(session, reviewed, "reviewed", user="tester")["idempotent"]
    assert apply_bundle(session, original, "original", user="tester")["idempotent"]
    # A fresh official import hash still repeats the unreviewed source row.
    apply_bundle(session, original, "original-repacked", user="tester")
    session.commit()
    offer = session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"])
    assert offer.promotion_type == "final_price" and offer.offer_state == "active"
    assert offer.price == 19900 and offer.original_price is None and offer.discount_rate is None
    assert offer.raw_record_id == "ingestion:10:0"
    assert offer.raw_evidence["observations"] == original["offers"][0]["raw_evidence"]["observations"]
    assert offer.audit_provenance["offer_interpretation_review"] == reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]
    assert offer.audit_provenance["review_reasons"] == ["unknown_promotion"]  # Historical audit retained.
    terms = offer.raw_evidence["promotion_conditions"]
    assert terms["membership_required"] is None and terms["coupon_required"] is None
    assert terms.get("minimum_quantity") == (2 if family == "minimum_order2_without_discount" else None)
    assert offer.event_name == original["offers"][0]["event_name"]
    assert offer.valid_from is None and offer.valid_to is None
    assert offer.standard_unit_price == round(19900 / (120 * 24) * 100, 4)
    assert offer.price_per_100g is None
    assert session.get(NormalizedCanonicalProduct, "prod-chocoemong").is_active
    assert session.get(NormalizedCanonicalProduct, "prod-chocoemong-pending").is_active is False
    assert session.get(NormalizedOfferEvent, "offer-emart-1-20260830-pending").offer_state == "pending_review"
    assert session.query(NormalizedOfferEvent).count() == 2


@pytest.mark.parametrize("change", ["price", "payload", "observation", "source_key", "source_url",
                                    "package_quantity", "package_unit", "variant_name", "attributes", "category"])
def test_offer_interpretation_review_rejects_changed_historical_binding(change):
    session = _session()
    original = _offer_review_fixture()
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original)
    apply_bundle(session, reviewed, "reviewed", user="tester")
    session.commit()
    changed = deepcopy(original)
    if change == "price":
        changed["offers"][0]["price"] = 20900
    elif change in {"payload", "observation"}:
        observation = changed["offers"][0]["raw_evidence"]["observations"][0]
        if change == "payload":
            observation["raw_payload"]["sale_price"] = 20900
            observation["raw_payload_sha256"] = _offer_review_digest(observation["raw_payload"])
        else:
            observation["capture_note"] = "changed historical observation"
    elif change.startswith("source_"):
        changed["source_listings"][0]["source_record_key" if change == "source_key" else "source_url"] += "changed"
    elif change == "category":
        changed["categories"].append({"id": "food.dairy.milk.other", "parent_id": "food.dairy.milk", "name_ko": "기타우유"})
        changed["products"][0]["unified_category_id"] = "food.dairy.milk.other"
    else:
        variant = changed["variants"][0]
        variant[change] = {"extra": "changed"} if change == "attributes" else {
            "package_quantity": 240, "package_unit": "g", "variant_name": "changed SKU"}[change]
    validation = validate_bundle(session, changed, "changed")
    assert not validation.ok
    assert any("offer_interpretation_review" in error for error in validation.errors)
    with pytest.raises(ValueError):
        apply_bundle(session, changed, "changed", user="tester")
    assert session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"]).price == 19900


def _category_refinement_fixture():
    from services.initial_taxonomy import taxonomy_categories
    original = _offer_review_fixture()
    title = "마시멜로 120g × 24 / 최소구매 2"
    listing = original["source_listings"][0]
    listing.update(source_title=title, source_record_key="555", source_url="https://www.costco.co.kr/Foods/Snack/CookieCracker/Marshmallow/p/555")
    original["categories"] = taxonomy_categories({"food.snacks.sweets.candy", "food.snacks.sweets.marshmallow"})
    original["products"][0].update(unified_category_id="food.snacks.sweets.candy", canonical_name=title)
    original["variants"][0].update(variant_name=title, package_unit="g", standard_unit="g", display_unit="120g × 24")
    for key in ("keywords", "match_rules", "mart_category_mappings"):
        original[key] = []
    observation = original["offers"][0]["raw_evidence"]["observations"][0]
    observation["raw_payload"].update(name=title, source_url=listing["source_url"], category="과자")
    observation["raw_payload_sha256"] = _offer_review_digest(observation["raw_payload"])
    original["offers"][0]["raw_evidence"]["promotion_conditions"] = {"source_title_purchase_condition": title}
    reviewed = _offer_review_payload(original)
    refined = deepcopy(reviewed)
    refined["products"][0]["unified_category_id"] = "food.snacks.sweets.marshmallow"
    review = reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]
    before = {key: value for key, value in review["binding"].items()
              if key not in {"public_offer_event_id", "quote", "observations"}}
    after = {**before, "unified_category_id": "food.snacks.sweets.marshmallow"}
    refined["offers"][0]["audit_provenance"]["offer_category_context_history"] = [{
        "version": 1, "status": "approved", "reason": "supported_category_form_refinement",
        "approved_by": "synthetic-moderator", "approved_at": "2026-10-04T01:00:00Z",
        "original_review_sha256": _offer_review_digest(review), "before_context": before, "after_context": after,
        "before_context_sha256": _offer_review_digest(before), "after_context_sha256": _offer_review_digest(after),
        "observations": deepcopy(review["binding"]["observations"])}]
    return original, reviewed, refined


def test_approved_category_refinement_preserves_original_review_quote_and_source_replay():
    original, reviewed, refined = _category_refinement_fixture()
    session = _session()
    for name, bundle in (("original", original), ("reviewed", reviewed), ("refined", refined)):
        apply_bundle(session, bundle, name, user="moderator")
        session.commit()
    assert apply_bundle(session, refined, "refined", user="moderator")["idempotent"]
    # Replay raw source observations without replacing the now-refined product.
    replay = deepcopy(original)
    replay["products"] = []
    apply_bundle(session, replay, "source-repacked", user="moderator")
    session.commit()
    offer = session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"])
    assert offer.audit_provenance["offer_interpretation_review"] == reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]
    assert offer.audit_provenance["offer_category_context_history"] == refined["offers"][0]["audit_provenance"]["offer_category_context_history"]
    assert offer.price == 19900 and offer.raw_evidence["observations"] == original["offers"][0]["raw_evidence"]["observations"]
    assert offer.promotion_type == "final_price" and offer.offer_state == "active"
    assert session.get(NormalizedCanonicalProduct, "prod-chocoemong").unified_category_id == "food.snacks.sweets.marshmallow"
    assert not validate_bundle(session, original, "stale-category").ok


@pytest.mark.parametrize("change", ["unapproved", "unbound_category", "source", "spec", "quote", "observation", "history", "old_review", "missing_history", "orphan_history"])
def test_approved_category_refinement_rejects_noncategory_changes_or_rewritten_history(change):
    original, reviewed, refined = _category_refinement_fixture()
    session = _session()
    for name, bundle in (("original", original), ("reviewed", reviewed)):
        apply_bundle(session, bundle, name, user="moderator")
        session.commit()
    transition = refined["offers"][0]["audit_provenance"]["offer_category_context_history"][0]
    if change == "unapproved": transition["status"] = "pending"
    elif change == "unbound_category":
        transition["after_context"]["unified_category_id"] = refined["products"][0]["unified_category_id"] = "food.snacks.sweets.jelly"
        refined["categories"].append({"id": "food.snacks.sweets.jelly", "parent_id": "food.snacks.sweets", "name_ko": "젤리"})
        transition["after_context_sha256"] = _offer_review_digest(transition["after_context"])
    elif change == "source": refined["source_listings"][0]["source_record_key"] = "different"
    elif change == "spec": refined["variants"][0]["package_quantity"] = 240
    elif change == "quote": refined["offers"][0]["price"] = 20000
    elif change == "observation": transition["observations"][0]["raw_payload_sha256"] = "0" * 64
    elif change == "old_review": refined["offers"][0]["audit_provenance"]["offer_interpretation_review"]["family"] = "informationalannotations"
    elif change == "missing_history": refined["offers"][0]["audit_provenance"].pop("offer_category_context_history")
    elif change == "orphan_history":
        unreviewed = _session()
        apply_bundle(unreviewed, original, "only-original", user="moderator")
        refined["offers"][0]["audit_provenance"].pop("offer_interpretation_review")
        session = unreviewed
    else:
        apply_bundle(session, refined, "refined", user="moderator")
        session.commit()
        transition["approved_by"] = "replacement-actor"
    assert not validate_bundle(session, refined, "invalid-transition").ok


@pytest.mark.parametrize("forgery", ["membership", "coupon", "free", "unsupported_family", "quote", "unbound_new_event", "top_level_terms", "malformed_evidence", "malformed_observation", "malformed_actor"])
def test_offer_interpretation_review_rejects_unproven_approval(forgery):
    session = _session()
    original = _offer_review_fixture()
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original)
    offer = reviewed["offers"][0]
    review = offer["audit_provenance"]["offer_interpretation_review"]
    if forgery in {"membership", "coupon"}:
        review["interpretation"]["promotion_conditions"][forgery + "_required"] = False
    elif forgery == "free":
        review["interpretation"]["promotion_conditions"]["free_quantity"] = 1
    elif forgery == "unsupported_family":
        review["family"] = "all_unknown_promotions"
    elif forgery == "quote":
        review["binding"]["quote"]["price"] = 1
    elif forgery == "unbound_new_event":
        offer["public_offer_event_id"] = "offer-new-price"
        review["binding"]["public_offer_event_id"] = "offer-new-price"
        reviewed["offer_week_links"] = []
    elif forgery == "top_level_terms":
        offer["promotion_conditions"] = {"coupon_required": False}
    elif forgery == "malformed_evidence":
        offer["raw_evidence"] = "not an evidence object"
    elif forgery == "malformed_observation":
        offer["raw_evidence"]["observations"] = ["not an observation object"]
    else:
        review["approved_by"] = ["not an authenticated actor name"]
    assert not validate_bundle(session, reviewed, "forged").ok
    with pytest.raises(ValueError):
        apply_bundle(session, reviewed, "forged", user="tester")
    assert session.get(NormalizedCanonicalProduct, "prod-chocoemong").is_active is False


def test_offer_interpretation_review_new_price_has_same_product_but_separate_unapproved_event():
    session = _session()
    original = _offer_review_fixture()
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    apply_bundle(session, _offer_review_payload(original), "reviewed", user="tester")
    session.commit()
    new_quote = deepcopy(original)
    offer = new_quote["offers"][0]
    offer.update(public_offer_event_id="offer-next-quote", price=20900, crawled_at="2026-08-31T00:00:00Z")
    observation = offer["raw_evidence"]["observations"][0]
    observation["raw_record_id"] = offer["raw_record_id"] = "ingestion:11:0"
    observation["raw_payload"].update(price=20900, sale_price=20900)
    observation["raw_payload_sha256"] = _offer_review_digest(observation["raw_payload"])
    new_quote["offer_week_links"] = []
    apply_bundle(session, new_quote, "new-price", user="tester")
    session.commit()
    old = session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"])
    new = session.get(NormalizedOfferEvent, "offer-next-quote")
    assert old.price == 19900 and old.promotion_type == "final_price" and old.offer_state == "active"
    assert new.price == 20900 and new.promotion_type == "unknown" and new.offer_state == "pending_review"
    assert "offer_interpretation_review" not in new.audit_provenance
    assert session.query(NormalizedCanonicalProduct).count() == 1
    assert session.query(NormalizedProductVariant).count() == 1
    assert session.query(NormalizedSourceListing).count() == 1
    assert session.query(NormalizedOfferEvent).count() == 2


@pytest.mark.parametrize("source_claim", ["buy_free_title", "checkout", "member", "discount"])
def test_offer_interpretation_review_rejects_conflicting_original_source_terms(source_claim):
    session = _session()
    original = _offer_review_fixture()
    listing, offer = original["source_listings"][0], original["offers"][0]
    observation = offer["raw_evidence"]["observations"][0]
    raw = observation["raw_payload"]
    if source_claim == "buy_free_title":
        listing["source_title"] += " / 1+1"
        raw["name"] = listing["source_title"]
        offer["raw_evidence"]["promotion_conditions"]["source_title_purchase_condition"] = listing["source_title"]
    else:
        raw[{"checkout": "checkout_price", "member": "membership_required", "discount": "discount_rate"}[source_claim]] = {
            "checkout": 14900, "member": True, "discount": 30}[source_claim]
    observation["raw_payload_sha256"] = _offer_review_digest(raw)
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original)
    validation = validate_bundle(session, reviewed, "reviewed")
    assert not validation.ok
    assert any("offer_interpretation_review" in error for error in validation.errors)


def test_offer_interpretation_review_requires_stored_original_pending_state_but_accepts_reviewed_incoming_shape():
    session = _session()
    original = _offer_review_fixture()
    reviewed = _offer_review_payload(original)
    review = reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]
    after = review["interpretation"]
    reviewed["offers"][0].update(promotion_type=after["promotion_type"], offer_state=after["offer_state"])
    reviewed["offers"][0]["raw_evidence"]["promotion_conditions"] = deepcopy(after["promotion_conditions"])
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    assert validate_bundle(session, reviewed, "reviewed").ok
    apply_bundle(session, reviewed, "reviewed", user="tester")
    session.commit()
    assert session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"]).offer_state == "active"

    other_session = _session()
    unreviewed_active = deepcopy(reviewed)
    unreviewed_active["offers"][0]["audit_provenance"] = {}
    apply_bundle(other_session, unreviewed_active, "unreviewed-active", user="tester")
    other_session.commit()
    validation = validate_bundle(other_session, reviewed, "forged-review-after-state")
    assert not validation.ok
    assert any("offer_interpretation_review" in error for error in validation.errors)


@pytest.mark.parametrize("event,kind,selection,benefit", [
    ("3개씩 골라 담으면, 그 중 1개는 무료", "selected_free_item", 3, 1),
    ("4개씩 골라 담으면, 50% 할인", "selected_percentage_discount", 4, 50.0),
    ("2개씩 골라 담으면, 10,000원", "selected_basket_total", 2, 10000),
    ("2개씩 골라 담으면, 10,000원 할인", "selected_won_discount", 2, 10000),
    pytest.param("2개씩 담으면, 50% 할인", "selected_percentage_discount", 2, 50.0,
                 id="literal_without_golla_0430000719969"),
])
@pytest.mark.parametrize("incoming_after", [False, True])
def test_conditional_selection_review_preserves_quote_and_sticky_unknown_payable_price(event, kind, selection, benefit, incoming_after):
    session = _session()
    family = "conditional_selection_observation"
    original = _offer_review_fixture(family, event)
    apply_bundle(session, original, "conditional-original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    review = reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]
    if incoming_after:
        reviewed["offers"][0]["offer_state"] = "active"
        reviewed["offers"][0]["raw_evidence"]["promotion_conditions"] = deepcopy(review["interpretation"]["promotion_conditions"])
    # Caller-provided derived rates cannot turn source conditions into a price.
    reviewed["offers"][0].update(standard_unit_price=1, price_per_100g=1, discount_rate=0.5)
    apply_bundle(session, reviewed, "conditional-reviewed", user="synthetic-moderator")
    session.commit()
    assert apply_bundle(session, reviewed, "conditional-reviewed", user="tester")["idempotent"]
    assert apply_bundle(session, original, "conditional-original", user="tester")["idempotent"]
    apply_bundle(session, original, "conditional-original-repacked", user="tester")
    session.commit()
    after_replay = deepcopy(reviewed)
    after_replay["offers"][0]["offer_state"] = "active"
    after_replay["offers"][0]["raw_evidence"]["promotion_conditions"] = deepcopy(review["interpretation"]["promotion_conditions"])
    apply_bundle(session, after_replay, "conditional-after-repacked", user="tester")
    session.commit()
    offer = session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"])
    assert offer.offer_state == "active" and offer.promotion_type == "unknown"
    assert offer.price == 19900 and offer.original_price is None
    assert offer.event_name == event and offer.valid_from is None and offer.valid_to is None
    assert offer.standard_unit_price is None and offer.price_per_100g is None and offer.discount_rate is None
    assert offer.raw_evidence["observations"] == original["offers"][0]["raw_evidence"]["observations"]
    assert offer.audit_provenance["offer_interpretation_review"] == review
    terms = offer.raw_evidence["promotion_conditions"]
    assert terms["condition_text"] == event and terms["source_condition_kind"] == kind
    assert terms["required_selection_quantity"] == selection
    benefit_field = {"selected_free_item": "conditional_free_quantity",
                     "selected_percentage_discount": "conditional_discount_percent",
                     "selected_basket_total": "conditional_basket_total_won",
                     "selected_won_discount": "conditional_discount_won"}[kind]
    assert terms[benefit_field] == benefit
    assert terms["basket_selection_required"] is True and terms["payable_price_unconfirmed"] is True
    assert terms["membership_required"] is None and terms["coupon_required"] is None
    assert "buy_quantity" not in terms and "free_quantity" not in terms and "minimum_quantity" not in terms
    from core.promotion_semantics import comparable_transaction_or_none
    assert comparable_transaction_or_none(current_price=offer.price, promotion_type=offer.promotion_type,
                                          promotion_conditions=terms) is None
    assert session.get(NormalizedCanonicalProduct, "prod-chocoemong").is_active
    assert session.query(NormalizedOfferEvent).count() == 1


@pytest.mark.parametrize("field,value,free", [
    ("required_selection_quantity", 2.0, False),
    ("conditional_discount_percent", 50, False),
    ("basket_selection_required", 1, False),
    ("payable_price_unconfirmed", 1, False),
    ("discount_application_unconfirmed", 1, False),
    ("conditional_free_quantity", True, True),
    ("conditional_free_quantity", 1.0, True),
    ("free_item_valuation_unconfirmed", 1, True),
    ("free_quantity", 1, True),
    ("membership_required", False, False),
    ("coupon_required", True, False),
])
def test_conditional_selection_review_rejects_forged_terms_and_json_type_changes(field, value, free):
    session = _session()
    family = "conditional_selection_observation"
    event = "3개씩 골라 담으면, 그 중 1개는 무료" if free else "2개씩 골라 담으면, 50% 할인"
    original = _offer_review_fixture(family, event)
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    review = reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]
    review["interpretation"]["promotion_conditions"][field] = value
    validation = validate_bundle(session, reviewed, "forged-conditional")
    assert not validation.ok
    assert any("offer_interpretation_review" in error for error in validation.errors)
    with pytest.raises(ValueError):
        apply_bundle(session, reviewed, "forged-conditional", user="tester")
    assert session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"]).offer_state == "pending_review"


@pytest.mark.parametrize("change", ["price", "quantity", "unit", "url", "raw_quote", "incoming_terms_type", "fake_final_price"])
def test_conditional_selection_review_rejects_changed_historical_context(change):
    session = _session()
    family = "conditional_selection_observation"
    original = _offer_review_fixture(family)
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    offer = reviewed["offers"][0]
    if change == "price":
        offer["price"] += 1
    elif change in {"quantity", "unit"}:
        reviewed["variants"][0]["package_quantity" if change == "quantity" else "package_unit"] = 240 if change == "quantity" else "g"
    elif change == "url":
        reviewed["source_listings"][0]["source_url"] += "-other"
    elif change == "raw_quote":
        observation = offer["raw_evidence"]["observations"][0]
        observation["raw_payload"]["sale_price"] += 1
        observation["raw_payload_sha256"] = _offer_review_digest(observation["raw_payload"])
    elif change == "incoming_terms_type":
        offer["offer_state"] = "active"
        offer["raw_evidence"]["promotion_conditions"] = deepcopy(offer["audit_provenance"]["offer_interpretation_review"]["interpretation"]["promotion_conditions"])
        offer["raw_evidence"]["promotion_conditions"]["payable_price_unconfirmed"] = 1
    else:
        offer["audit_provenance"]["offer_interpretation_review"]["interpretation"]["promotion_type"] = "final_price"
    assert not validate_bundle(session, reviewed, "changed-conditional").ok
    with pytest.raises(ValueError):
        apply_bundle(session, reviewed, "changed-conditional", user="tester")


@pytest.mark.parametrize("source_change", ["checkout", "malformed_suffix", "malformed_money", "membership", "different_native"])
def test_conditional_selection_review_cannot_approve_unsupported_original_source(source_change):
    session = _session()
    family = "conditional_selection_observation"
    unsupported = {"checkout": "농할 할인 20%_결제시 자동적용",
                   "malformed_suffix": "2개씩 골라 담으면, 1,000원 할인 추가",
                   "malformed_money": "3개씩 골라 담으면, 9,90원"}
    original = _offer_review_fixture(family, unsupported.get(source_change))
    observation = original["offers"][0]["raw_evidence"]["observations"][0]
    if source_change == "membership":
        observation["raw_payload"]["attributes"]["membership_required"] = True
    elif source_change == "different_native":
        observation["raw_payload"]["source_url"] = "https://lottemartzetta.com/products/OSother/details"
    observation["raw_payload_sha256"] = _offer_review_digest(observation["raw_payload"])
    apply_bundle(session, original, "original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    validation = validate_bundle(session, reviewed, "unsupported-conditional")
    assert not validation.ok
    assert any("offer_interpretation_review" in error for error in validation.errors)


@pytest.mark.parametrize("event,program,stage,method", [
    ("농할 할인 20%_결제시 자동적용", "농할", "checkout", "automatic"),
    ("수산대전 20% 할인", "수산대전", None, None),
])
def test_conditional_program_review_sticky_replay_preserves_unknown_payment_and_new_price_identity(event, program, stage, method):
    session = _session()
    family = "conditional_program_observation"
    original = _offer_review_fixture(family, event)
    apply_bundle(session, original, "program-original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    # Neither review status nor an incoming derived number establishes payment.
    reviewed["offers"][0].update(standard_unit_price=1, price_per_100g=1, discount_rate=0.2)
    apply_bundle(session, reviewed, "program-reviewed", user="synthetic-moderator")
    session.commit()
    assert apply_bundle(session, reviewed, "program-reviewed", user="tester")["idempotent"]
    assert apply_bundle(session, original, "program-original", user="tester")["idempotent"]
    apply_bundle(session, original, "program-original-repacked", user="tester")
    session.commit()
    review = reviewed["offers"][0]["audit_provenance"]["offer_interpretation_review"]
    after = deepcopy(reviewed)
    after["offers"][0]["offer_state"] = "active"
    after["offers"][0]["raw_evidence"]["promotion_conditions"] = deepcopy(review["interpretation"]["promotion_conditions"])
    apply_bundle(session, after, "program-after-repacked", user="tester")
    session.commit()
    old = session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"])
    assert old.price == 19900 and old.event_name == event
    assert old.promotion_type == "unknown" and old.offer_state == "active"
    assert old.discount_rate is None and old.standard_unit_price is None and old.price_per_100g is None
    assert old.raw_evidence["observations"] == original["offers"][0]["raw_evidence"]["observations"]
    assert old.audit_provenance["offer_interpretation_review"] == review
    terms = old.raw_evidence["promotion_conditions"]
    assert terms["condition_text"] == event and terms["source_program_name"] == program
    assert terms["conditional_discount_percent"] == 20 and type(terms["conditional_discount_percent"]) is int
    assert terms["source_declared_application_stage"] == stage and terms["source_declared_application_method"] == method
    assert terms["payable_price_unconfirmed"] is True and terms["program_eligibility_unconfirmed"] is True
    assert terms["benefit_cap"] is None and terms["discount_calculation_basis"] is None
    assert terms["membership_required"] is None and terms["coupon_required"] is None
    from core.promotion_semantics import comparable_transaction_or_none
    assert comparable_transaction_or_none(current_price=old.price, promotion_type=old.promotion_type,
                                          promotion_conditions=terms) is None
    assert session.get(NormalizedCanonicalProduct, "prod-chocoemong").is_active
    new_quote = deepcopy(original)
    new = new_quote["offers"][0]
    new.update(public_offer_event_id="program-next-price", price=20900, crawled_at="2026-08-31T00:00:00Z", raw_record_id="ingestion:11:0")
    observation = new["raw_evidence"]["observations"][0]
    observation["raw_record_id"] = "ingestion:11:0"
    observation["raw_payload"].update(price=20900, sale_price=20900)
    observation["raw_payload_sha256"] = _offer_review_digest(observation["raw_payload"])
    new_quote["offer_week_links"] = []
    apply_bundle(session, new_quote, "program-new-price", user="tester")
    session.commit()
    next_event = session.get(NormalizedOfferEvent, "program-next-price")
    assert next_event.price == 20900 and next_event.offer_state == "pending_review"
    assert "offer_interpretation_review" not in next_event.audit_provenance
    assert old.price == 19900 and old.audit_provenance["offer_interpretation_review"] == review
    assert session.query(NormalizedCanonicalProduct).count() == 1
    assert session.query(NormalizedProductVariant).count() == 1
    assert session.query(NormalizedSourceListing).count() == 1
    assert session.query(NormalizedOfferEvent).count() == 2


@pytest.mark.parametrize("change", ["wrong_event", "wrong_url", "wrong_spec", "raw_quote", "float_rate",
                                    "integer_flag", "extra_eligibility", "inferred_application"])
def test_conditional_program_review_rejects_wrong_source_context_types_or_qualifications(change):
    session = _session()
    family = "conditional_program_observation"
    event = "농할 할인 30%_결제시 자동적용" if change == "wrong_event" else "수산대전 20% 할인"
    original = _offer_review_fixture(family, event)
    apply_bundle(session, original, "program-original", user="tester")
    session.commit()
    reviewed = _offer_review_payload(original, family)
    offer = reviewed["offers"][0]
    terms = offer["audit_provenance"]["offer_interpretation_review"]["interpretation"]["promotion_conditions"]
    if change == "wrong_url":
        reviewed["source_listings"][0]["source_url"] += "-other"
    elif change == "wrong_spec":
        reviewed["variants"][0]["package_quantity"] = 240
    elif change == "raw_quote":
        observation = offer["raw_evidence"]["observations"][0]
        observation["raw_payload"]["sale_price"] = 20900
        observation["raw_payload_sha256"] = _offer_review_digest(observation["raw_payload"])
    elif change == "float_rate":
        terms["conditional_discount_percent"] = 20.0
    elif change == "integer_flag":
        terms["payable_price_unconfirmed"] = 1
    elif change == "extra_eligibility":
        terms["membership_required"] = False
    elif change == "inferred_application":
        terms["source_declared_application_method"] = "automatic"
    validation = validate_bundle(session, reviewed, "forged-program")
    assert not validation.ok
    assert any("offer_interpretation_review" in error for error in validation.errors)
    with pytest.raises(ValueError):
        apply_bundle(session, reviewed, "forged-program", user="tester")
    assert session.get(NormalizedOfferEvent, original["offers"][0]["public_offer_event_id"]).offer_state == "pending_review"


def _source_context_partition_fixture():
    from core.reviewed_content_quantities import REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
    from core.reviewed_source_evidence import _source_identity_context_proof
    reviews = [record for record in REVIEWED_SOURCE_OBSERVATION_ELIGIBILITY
               if (record.get("identity_context") or {}).get("source_record_key") == "069582950"]
    bundle = _bundle()
    category = reviews[0]["category_id"]
    path = category.split(".")
    bundle["categories"] = [{"id": ".".join(path[:index + 1]),
                              "parent_id": ".".join(path[:index]) if index else None,
                              "name_ko": path[index]} for index in range(len(path))]
    bundle.update(keywords=[], offers=[], offer_week_links=[], match_rules=[], mart_category_mappings=[])
    bundle["products"], bundle["variants"], bundle["source_listings"] = [], [], []
    for index, review in enumerate(reviews):
        proof = _source_identity_context_proof(review)
        source = {"source_name": proof["source_name"], "source_record_key": proof["source_record_key"],
                  **proof["required_source"]}
        bundle["products"].append({"public_product_id": f"context-product-{index}",
                                   "canonical_name": proof["title"], "unified_category_id": category})
        attributes = {"source_evidence_reviews": [source]}
        if proof['partition_key']:
            attributes['source_identity_context'] = proof
        bundle["variants"].append({"public_variant_id": f"context-variant-{index}",
                                   "public_product_id": f"context-product-{index}", "variant_name": proof["title"],
                                   "package_quantity": proof["normalized"][0], "package_unit": proof["normalized"][1],
                                   "bundle_count": proof["normalized"][2],
                                   "attributes": attributes})
        bundle["source_listings"].append({"public_source_listing_id": f"context-listing-{index}",
                                         "public_variant_id": f"context-variant-{index}",
                                         "source_name": proof["source_name"], "source_record_key": proof["source_record_key"],
                                         "source_title": proof["title"], "source_url": proof["required_source"]["source_urls"][0]})
    return bundle


def test_source_identity_context_partition_requires_two_complete_distinct_registered_contexts():
    session = _session()
    bundle = _source_context_partition_fixture()
    validation = validate_bundle(session, bundle, "partition")
    assert validation.ok, validation.errors
    apply_bundle(session, bundle, "partition", user="tester")
    session.commit()
    assert session.query(NormalizedSourceListing).count() == 2
    assert session.query(NormalizedCanonicalProduct).count() == 2
    assert 'source_identity_context' not in bundle['variants'][0]['attributes']
    assert bundle['variants'][1]['attributes']['source_identity_context']['partition_key'] == 'grade-unspecified'


@pytest.mark.parametrize("change", ["no_proof", "null_proof", "missing_source_reviews", "quantity", "title", "url", "category", "same_product", "repeated_partition"])
def test_source_identity_context_partition_rejects_unreviewed_or_reused_context(change):
    session = _session()
    bundle = _source_context_partition_fixture()
    variant, listing = bundle["variants"][1], bundle["source_listings"][1]
    if change == "no_proof":
        variant["attributes"] = {}
    elif change == "null_proof":
        variant["attributes"]["source_identity_context"] = None
    elif change == "missing_source_reviews":
        variant["attributes"]["source_evidence_reviews"] = None
    elif change == "quantity":
        variant["package_quantity"] += 1
    elif change == "title":
        listing["source_title"] += "changed"
    elif change == "url":
        listing["source_url"] = "https://example.test/069582950"
    elif change == "category":
        bundle["categories"].append({"id": "food.produce.fruit.other", "parent_id": "food.produce.fruit", "name_ko": "other"})
        bundle["products"][1]["unified_category_id"] = "food.produce.fruit.other"
    elif change == "same_product":
        variant["public_product_id"] = bundle["products"][0]["public_product_id"]
    else:
        # A third listing cannot cycle back to the first partition merely
        # because it differs from the immediately preceding listing.
        product, variant, listing = (deepcopy(bundle[key][0]) for key in ("products", "variants", "source_listings"))
        product["public_product_id"] = variant["public_product_id"] = "context-product-third"
        variant["public_variant_id"] = listing["public_variant_id"] = "context-variant-third"
        listing["public_source_listing_id"] = "context-listing-third"
        for key, row in (("products", product), ("variants", variant), ("source_listings", listing)):
            bundle[key].append(row)
    validation = validate_bundle(session, bundle, "invalid-partition")
    assert not validation.ok
    assert any("중복 마트 원본 ID" in error for error in validation.errors)


@pytest.mark.parametrize("attributes", ["malformed attributes", [], 7])
def test_source_identity_context_partition_malformed_attributes_returns_validation_error(attributes):
    bundle = _source_context_partition_fixture()
    bundle["variants"][0]["attributes"] = attributes
    session = _session()
    validation = validate_bundle(session, bundle, "malformed-context")
    assert not validation.ok
    assert any("attributes" in error for error in validation.errors)
    with pytest.raises(ValueError):
        apply_bundle(session, bundle, "malformed-context", user="tester")
    assert session.query(NormalizedSourceListing).count() == 0


def test_reimport_same_offer_from_new_ingestion_preserves_both_raw_observations():
    session = _session()
    bundle = _bundle()
    offer = bundle["offers"][0]
    for ingestion in (10, 11):
        raw_id = f"ingestion:{ingestion}:0"
        offer["raw_record_id"] = raw_id
        offer["raw_evidence"] = {"observations": [{"raw_record_id": raw_id, "raw_payload": {"price": 19900}}]}
        offer["audit_provenance"] = {"raw_record_ids": [raw_id], "source_ingestion_ids": [ingestion], "observation_count": 1}
        apply_bundle(session, bundle, f"hash-{ingestion}", user="tester")
        session.commit()
    stored = session.get(NormalizedOfferEvent, offer["public_offer_event_id"])
    assert session.query(NormalizedOfferEvent).count() == 1
    assert stored.raw_record_id == "ingestion:10:0"
    assert stored.audit_provenance["source_ingestion_ids"] == [10, 11]
    assert stored.audit_provenance["observation_count"] == 2
    assert len(stored.raw_evidence["observations"]) == 2


def test_manifest_rejects_dropped_original_observation():
    session = _session()
    bundle = _bundle()
    bundle["source_manifest"] = {"source_ingestions": [{"id": 1, "items_count": 1}], "observation_count": 1}
    bundle["observation_accounting"] = []
    validation = validate_bundle(session, bundle, "hash")
    assert not validation.ok
    assert any("원본 행" in error for error in validation.errors)


def test_catalog_bundle_apply_is_atomic_shape_and_idempotent():
    session = _session()
    bundle = _bundle()
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()

    validation = validate_bundle(session, bundle, digest)
    assert validation.ok, validation.errors
    first = apply_bundle(session, bundle, digest, user="tester")
    session.commit()
    second = apply_bundle(session, bundle, digest, user="tester")

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert session.query(UnifiedCategory).count() == 4
    assert session.query(Keyword).count() == 1
    assert session.query(NormalizedCanonicalProduct).count() == 1
    assert session.query(NormalizedProductVariant).count() == 1
    assert session.query(NormalizedOfferEvent).count() == 1
    assert [row.level for row in session.execute(select(UnifiedCategory).order_by(UnifiedCategory.level)).scalars()] == [0, 1, 2, 3]
    rule = session.execute(select(MatchingEntry)).scalar_one()
    assert rule.public_product_id == "prod-chocoemong"
    assert rule.public_variant_id == "var-chocoemong-120ml-24"
    keyword = session.execute(select(Keyword)).scalar_one()
    assert keyword.unified_category_id == "food.dairy.milk.chocolate"
    assert keyword.category_id is None
    assert keyword.synonyms == ["초콜릿우유", "chocolate milk"]

    # An approved specification correction moves the stable source listing and
    # matching target, while preserving the old ID and original offer history.
    corrected = deepcopy(bundle)
    old_id = corrected["variants"][0]["public_variant_id"]
    new_id = "var-reviewed-corrected-spec"
    corrected["variants"][0].update(public_variant_id=new_id, package_quantity=240)
    corrected["source_listings"][0]["public_variant_id"] = new_id
    corrected["match_rules"][0].update(public_variant_id=new_id, pack_qty=240)
    result = apply_bundle(session, corrected, "reviewed-specification-correction", user="tester")
    session.commit()
    assert result["preserved_inactive_superseded_variant_ids"] == [old_id]
    assert session.get(NormalizedProductVariant, old_id).package_quantity == 120
    assert session.get(NormalizedProductVariant, old_id).is_active is False
    assert session.get(NormalizedProductVariant, new_id).is_active is True
    assert session.query(NormalizedOfferEvent).count() == 1
    assert session.query(NormalizedSourceListing).count() == 1
    assert apply_bundle(session, corrected, "reviewed-specification-correction", user="tester")["idempotent"] is True


def test_category_cycle_and_fifth_level_are_rejected():
    session = _session()
    cycle = _bundle()
    cycle["categories"][0]["parent_id"] = "food.dairy.milk.chocolate"
    assert not validate_bundle(session, cycle, "cycle").ok

    too_deep = _bundle()
    too_deep["categories"].append({
        "id": "food.dairy.milk.chocolate.small",
        "parent_id": "food.dairy.milk.chocolate",
        "name_ko": "소용량",
    })
    assert any("4단계를 초과" in error for error in validate_bundle(session, too_deep, "deep").errors)


def test_product_must_use_leaf_and_low_confidence_requires_approval():
    session = _session()
    internal = _bundle()
    internal["products"][0]["unified_category_id"] = "food.dairy.milk"
    assert any("리프" in error for error in validate_bundle(session, internal, "internal").errors)

    low = _bundle()
    low["products"][0]["classification_confidence"] = 0.79
    assert any("approved" in error for error in validate_bundle(session, low, "low").errors)
    low["products"][0]["review_status"] = "approved"
    approved = validate_bundle(session, low, "approved")
    assert approved.ok
    assert approved.review_counts["low_confidence_approved"] == 1


def test_json_parser_populates_optional_entities():
    content = json.dumps({"schema_version": SCHEMA_VERSION, "run_id": "x"}).encode()
    bundle, digest = parse_bundle(content)
    assert digest == hashlib.sha256(content).hexdigest()
    assert bundle["keywords"] == []
    assert bundle["products"] == []


def test_keyword_definitions_require_unified_category_and_clean_unique_terms():
    session = _session()

    missing_category = _bundle()
    missing_category["keywords"][0]["unified_category_id"] = "missing"
    result = validate_bundle(session, missing_category, "missing-category")
    assert any("없는 통합 카테고리" in error for error in result.errors)

    duplicate_synonym = _bundle()
    duplicate_synonym["keywords"][0]["synonyms"] = ["초코우유"]
    result = validate_bundle(session, duplicate_synonym, "duplicate-synonym")
    assert any("중복 synonym" in error for error in result.errors)

    duplicate_word = _bundle()
    duplicate_word["keywords"].append({**duplicate_word["keywords"][0]})
    result = validate_bundle(session, duplicate_word, "duplicate-word")
    assert any("중복 word" in error for error in result.errors)


def test_keyword_definition_upsert_preserves_search_count():
    session = _session()
    keyword = Keyword(
        word="초코우유",
        synonyms=["old"],
        category_id=None,
        search_count=17,
        is_active=False,
    )
    session.add(keyword)
    session.commit()

    bundle = _bundle()
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()
    apply_bundle(session, bundle, digest, user="tester")
    session.commit()

    session.refresh(keyword)
    assert keyword.search_count == 17
    assert keyword.is_active is True
    assert keyword.synonyms == ["초콜릿우유", "chocolate milk"]
    assert keyword.unified_category_id == "food.dairy.milk.chocolate"


def test_imported_category_level_is_derived_from_parent_tree():
    session = _session()
    bundle = _bundle()
    for row in bundle["categories"]:
        row["level"] = 0
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()

    apply_bundle(session, bundle, digest, user="tester")
    session.flush()

    levels = {
        row.id: row.level
        for row in session.execute(select(UnifiedCategory)).scalars()
    }
    assert levels["food"] == 0
    assert levels["food.dairy.milk.chocolate"] == 3


def test_old_bundle_without_optional_keywords_still_validates_directly():
    bundle = _bundle()
    del bundle["keywords"]
    assert validate_bundle(_session(), bundle, "old").ok


def test_duplicate_listing_keys_and_equivalent_variant_specs_are_rejected():
    bundle = _bundle()
    bundle["source_listings"].append({
        **bundle["source_listings"][0], "public_source_listing_id": "duplicate-listing",
    })
    bundle["variants"].append({
        **bundle["variants"][0], "public_variant_id": "duplicate-variant",
        "package_quantity": 0.12, "package_unit": "L",
    })
    errors = validate_bundle(_session(), bundle, "duplicates").errors
    assert any("중복 마트 원본 ID" in error for error in errors)
    assert any("중복 variant" in error for error in errors)


def test_match_key_collision_and_wrong_variant_parent_are_rejected():
    bundle = _bundle()
    bundle["products"].append({**bundle["products"][0], "public_product_id": "other-product"})
    bundle["match_rules"].append({**bundle["match_rules"][0], "public_product_id": "other-product"})
    errors = validate_bundle(_session(), bundle, "wrong-target").errors
    assert any("중복 match_key" in error for error in errors)
    assert any("상품군에 속하지" in error for error in errors)


def test_malformed_package_and_entity_shapes_return_validation_errors():
    bundle = _bundle()
    bundle["variants"][0]["bundle_count"] = "not-a-number"
    assert not validate_bundle(_session(), bundle, "bad-count").ok
    bundle["products"] = [None]
    assert not validate_bundle(_session(), bundle, "bad-shape").ok


def test_unparsed_variant_unit_is_not_imported_as_public_variant():
    bundle = _bundle()
    bundle["variants"][0]["package_unit"] = "mystery"
    assert not validate_bundle(_session(), bundle, "unknown-unit").ok


@pytest.mark.parametrize("facility,unit,allowed", [
    (True, "인", False), (True, "인분", False),
    (True, "매", True), (False, "인분", True),
])
def test_facility_quantity_purpose_is_validated_before_import(facility, unit, allowed):
    bundle = _bundle()
    if facility:
        leaf = "services.facility.camping.cabin_package"
        bundle["categories"] = [
            {"id": "services", "parent_id": None, "name_ko": "서비스"},
            {"id": "services.facility", "parent_id": "services", "name_ko": "시설"},
            {"id": "services.facility.camping", "parent_id": "services.facility", "name_ko": "캠핑"},
            {"id": leaf, "parent_id": "services.facility.camping", "name_ko": "캐빈 패키지"},
        ]
        for rows in (bundle["products"], bundle["keywords"], bundle["mart_category_mappings"]):
            for row in rows:
                row["unified_category_id"] = leaf
    bundle["variants"][0].update(
        variant_name=f"이용권 2{unit}" if facility else "식사 2인분",
        package_quantity=2, package_unit=unit, bundle_count=1, display_unit=f"2{unit}",
    )
    original = deepcopy(bundle)
    result = validate_bundle(_session(), bundle, "quantity-purpose")
    assert result.ok is allowed, result.errors
    assert any("unit_service_occupancy_not_entitlement" in error for error in result.errors) is not allowed
    assert bundle == original


def test_facility_quantity_purpose_uses_persisted_parent_for_partial_bundle():
    session = _session()
    bundle = _bundle()
    leaf = "services.facility.camping.cabin_package"
    bundle["categories"] = [
        {"id": "services", "parent_id": None, "name_ko": "서비스"},
        {"id": "services.facility", "parent_id": "services", "name_ko": "시설"},
        {"id": "services.facility.camping", "parent_id": "services.facility", "name_ko": "캠핑"},
        {"id": leaf, "parent_id": "services.facility.camping", "name_ko": "캐빈 패키지"},
    ]
    for rows in (bundle["products"], bundle["keywords"], bundle["mart_category_mappings"]):
        for row in rows:
            row["unified_category_id"] = leaf
    bundle["variants"][0].update(variant_name="이용권 2매", package_quantity=2,
                                  package_unit="매", bundle_count=1, display_unit="2매")
    apply_bundle(session, bundle, "valid-tickets", user="synthetic-test")
    partial = deepcopy(bundle)
    partial["products"] = []
    partial["variants"][0].update(variant_name="캐빈 정원 2인", package_unit="인", display_unit="2인")
    result = validate_bundle(session, partial, "partial-occupancy")
    assert not result.ok
    assert any("unit_service_occupancy_not_entitlement" in error for error in result.errors)
    saved = session.get(NormalizedProductVariant, bundle["variants"][0]["public_variant_id"])
    assert saved.package_unit == "매" and saved.package_quantity == 2


def test_offer_timestamp_is_normalized_to_utc_on_import():
    session = _session()
    bundle = _bundle()
    bundle["offers"][0]["crawled_at"] = "2026-09-03T09:00:00+09:00"
    apply_bundle(session, bundle, "timezone", user="tester")
    offer = session.execute(select(NormalizedOfferEvent)).scalar_one()
    assert offer.crawled_at.isoformat() == "2026-09-03T00:00:00"


def _captured_quote_fixture(source, change=None):
    from services.catalog_bundle import _captured_native_quote_terms
    original, _ = _native_quote_fixture(source)
    offer = original['offers'][0]
    observation = offer['raw_evidence']['observations'][0]
    raw = observation['raw_payload']; attrs = raw['attributes']
    node = deepcopy(attrs['submission_business_evidence'][0]['raw_product_node'] if source == 'costco'
                    else attrs['lottemart_detail_source_fields'])
    capture = {'source_url': raw['source_url'], 'received_at': offer['crawled_at'],
               'raw_product_nodes': [{'raw_product_node': deepcopy(node)}]}
    marker = {'source_condition_kind': 'source_quote_purchase_conditions_unverified',
              'payable_price_unconfirmed': True, 'customer_eligibility_unconfirmed': True,
              'source_quote_currency': 'KRW'}
    if source == 'costco':
        attrs.pop('submission_business_evidence')
        native = original['source_listings'][0]['source_record_key']
        capture.update(source_url=f'https://www.costco.co.kr/rest/v2/korea/products/{native}/?fields=FULL&lang=ko&curr=KRW',
                       native_context=native)
        marker['source_native_business_conditions'] = {'membership': node.get('membership'),
              'minOrderQuantity': node.get('minOrderQuantity'), 'maxOrderQuantity': node.get('maxOrderQuantity'),
              'currency': node['price']['currencyIso'], 'maxOrderMode': 'not retained/unassessed'}
    else:
        marker.update(selection_group_eligibility_unconfirmed=True, source_promotion_text=offer['event_name'],
                      source_promotion_period_text='(2026.10.01 - 2026.10.14)',
                      source_native_business_conditions={'promotions': node['promotions'],
                         'quantityRestrictionGroup': node.get('quantityRestrictionGroup'),
                         'visible_promotion_date_text': '(2026.10.01 - 2026.10.14)', 'limits': 'unconfirmed payment'})
    if change == 'time':capture['received_at'] = '2026-08-31T00:00:00Z'
    if change == 'naive_time':capture['received_at'] = offer['crawled_at'].replace('Z', '')
    if change == 'unexpected_terms':marker['source_native_business_conditions']['checkout_price'] = offer['price']
    if change == 'url':capture['source_url'] += '?other=1'
    if change == 'native':
        if source == 'costco':capture['native_context'] = 'other-native'
        else:capture['raw_product_nodes'][0]['raw_product_node']['retailerProductId'] = 'OSother-native'
    if change == 'quote':
        if source == 'costco':capture['raw_product_nodes'][0]['raw_product_node']['price']['value'] += 100
        else:capture['raw_product_nodes'][0]['raw_product_node']['price']['amount'] = '4000'
    if change == 'eligibility':marker['customer_eligibility_unconfirmed'] = False
    text = json.dumps(capture, ensure_ascii=False)
    marker['source_capture_input_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    if change == 'hash':marker['source_capture_input_sha256'] = '0' * 64
    attrs['promotion_conditions'] = marker
    observation['raw_payload_sha256'] = _offer_review_digest(raw)
    offer['raw_evidence']['promotion_conditions'] = {'promotion_conditions': deepcopy(marker)}
    reviewed = _offer_review_payload(original, 'native_source_quote_purchase_conditions_unverified', source_quote_terms={})
    review = reviewed['offers'][0]['audit_provenance']['offer_interpretation_review']
    review['native_source_capture_utf8'] = text
    if change is None:
        _, terms = _captured_native_quote_terms(review, review['binding'], offer['raw_evidence'], original['variants'][0]['attributes'])
        review['interpretation']['promotion_conditions'] = {**terms, 'membership_required': None, 'coupon_required': None}
    return original, reviewed


@pytest.mark.parametrize('source', ['costco', 'lottemart'])
def test_captured_quote_review_preserves_original_receipt_and_sticky_reimport(source):
    original, reviewed = _captured_quote_fixture(source)
    session = _session()
    for index, bundle in enumerate((original, reviewed, {**deepcopy(original), 'run_id': 'capture-replay'}, reviewed)):
        parsed, digest = parse_bundle(json.dumps(bundle, ensure_ascii=False).encode(), 'capture.json')
        validation = validate_bundle(session, parsed, digest)
        assert validation.ok, validation.errors
        result = apply_bundle(session, parsed, digest, user='synthetic-moderator')
        assert result['idempotent'] is (index == 3)
    stored = session.get(NormalizedOfferEvent, original['offers'][0]['public_offer_event_id'])
    assert stored.raw_evidence['observations'] == original['offers'][0]['raw_evidence']['observations']
    assert stored.offer_state == 'active' and stored.promotion_type == 'unknown'
    assert stored.price == original['offers'][0]['price']
    assert stored.standard_unit_price is None and stored.price_per_100g is None
    assert stored.raw_evidence['promotion_conditions']['payable_price_unconfirmed'] is True
    assert 'minimum_quantity' not in stored.raw_evidence['promotion_conditions']
    session.close()


@pytest.mark.parametrize('source', ['costco', 'lottemart'])
@pytest.mark.parametrize('change', ['hash', 'time', 'naive_time', 'url', 'native', 'quote', 'eligibility', 'unexpected_terms'])
def test_captured_quote_review_rejects_wrong_receipt_or_payment_claim(source, change):
    original, reviewed = _captured_quote_fixture(source, change)
    session = _session()
    apply_bundle(session, original, 'original-capture', user='synthetic-moderator')
    validation = validate_bundle(session, reviewed, 'changed-capture')
    assert not validation.ok
    assert session.get(NormalizedOfferEvent, original['offers'][0]['public_offer_event_id']).offer_state == 'pending_review'
    session.close()


def test_formal_import_connects_only_active_category_keywords_and_preserves_targets():
    session = _session()
    bundle = _bundle()
    bundle['keywords'].append({'word': '우유', 'unified_category_id': 'food.dairy.milk', 'synonyms': []})
    bundle['products'][0]['keywords'] = ['원문 전용 검색어']
    apply_bundle(session, bundle, 'keyword-link-initial', user='synthetic-moderator')
    product = session.get(NormalizedCanonicalProduct, 'prod-chocoemong')
    rule = session.execute(select(MatchingEntry)).scalar_one()
    target = (rule.public_product_id, rule.public_variant_id, rule.match_key)
    ids = {keyword.word: keyword.id for keyword in session.execute(select(Keyword)).scalars()}
    assert product.keywords == ['우유', '원문 전용 검색어', '초코우유']
    assert rule.keyword_ids == sorted(ids.values())
    changed = deepcopy(bundle)
    changed['products'][0] = __import__('services.catalog_bundle', fromlist=['product_bundle_row']).product_bundle_row(product)
    changed['keywords'][0]['is_active'] = False
    apply_bundle(session, changed, 'keyword-deactivated', user='synthetic-moderator')
    assert product.keywords == ['우유', '원문 전용 검색어']
    assert rule.keyword_ids == [ids['우유']]
    assert (rule.public_product_id, rule.public_variant_id, rule.match_key) == target
    assert apply_bundle(session, changed, 'keyword-deactivated', user='synthetic-moderator')['idempotent'] is True
