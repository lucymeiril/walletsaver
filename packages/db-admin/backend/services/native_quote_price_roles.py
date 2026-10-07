"""Native standalone base quotes, separate from unapplied purchase benefits."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from urllib.parse import urlsplit

from core.match_key import normalize_pack_identity
from core.product_units import parse_package_quantity
from core.promotion_semantics import conditional_selection_facts_or_none


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _money(value):
    if isinstance(value, bool):
        raise ValueError("native base amount invalid")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("native base amount invalid")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("native base amount invalid")
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def native_lotte_price_roles(raw, attrs, title, *, expected_native=None, expected_url=None, expected_package=None):
    """Return source-base facts, or None for other producer shapes; never match on money."""
    node = attrs.get("lottemart_detail_source_fields")
    if node is None:
        return None
    if not isinstance(node, dict) or attrs.get("lottemart_detail_source_fields_sha256") != _digest(node):
        raise ValueError("native Lotte product hash mismatch")
    native = str(attrs.get("source_record_key") or "")
    if (not native or native != (expected_native or native) or node.get("retailerProductId") != "OS" + native
            or node.get("name") != title or raw.get("source_title", raw.get("name")) != title
            or node.get("type") != "REGULAR"):
        raise ValueError("native Lotte product identity/type mismatch")
    url = attrs.get("source_url")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (parsed is None or parsed.scheme != "https" or parsed.netloc != "lottemartzetta.com"
            or parsed.path != f"/products/OS{native}/details" or parsed.query or parsed.fragment
            or url != (expected_url or url)):
        raise ValueError("native Lotte product URL mismatch")
    try:
        stamp = datetime.fromisoformat(str(raw.get("crawled_at", "")).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("native base observation timestamp missing")
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("native base observation timestamp must be aware")
    package = parse_package_quantity(node.get("packSizeDescription", ""))
    supplied = expected_package or {"package_quantity":raw.get("package_quantity"),
                                   "package_unit":raw.get("package_unit"), "bundle_count":raw.get("bundle_count") or 1}
    if (not package or node['packSizeDescription'].strip() != package['raw_match']
            or normalize_pack_identity(package["package_quantity"], package["package_unit"])
            != normalize_pack_identity(supplied.get("package_quantity"), supplied.get("package_unit"))
            or package.get("bundle_count", 1) != supplied.get("bundle_count", 1)):
        raise ValueError("native base package declaration mismatch")
    price = node.get("price")
    if not isinstance(price, dict) or price.get("currency") != "KRW":
        raise ValueError("native base KRW amount required")
    amount = _money(price.get("amount"))
    for value in (raw.get("sale_price"), raw.get("current_price"), raw.get("price")):
        if value is not None and _money(value) != amount:
            raise ValueError("native base quote aliases conflict")
    promotions = node.get("promotions")
    if not isinstance(promotions, list) or any(not isinstance(p, dict) or not isinstance(p.get("description"), str)
            or not p["description"].strip() or p.get("type") != "OFFER" for p in promotions):
        raise ValueError("native promotion declarations malformed")
    if raw.get("event_name") != (" · ".join(p["description"] for p in promotions) or None):
        raise ValueError("native promotion declarations differ from event text")
    records = attrs.get("submission_business_evidence")
    if not isinstance(records, list) or not records:
        raise ValueError("original native business node required")
    for record in records:
        view = record.get("raw_product_node") if isinstance(record, dict) else None
        if (not isinstance(view, dict) or record.get('raw_product_node_sha256') != _digest(view)
                or record.get('http_receipt_status') != 'supplied_response_metadata'
                or record.get('source_response_url') != url
                or record.get('native_context') != native
                or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('source_response_body_sha256') or ''))
                or any(view.get(k) != node.get(k) for k in
                ("retailerProductId", "name", "type", "packSizeDescription", "price"))):
            raise ValueError("original native business/base view conflict")
        try:
            received = datetime.fromisoformat(str(record.get('source_response_received_at', '')).replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('native response receipt timestamp missing')
        if received.tzinfo is None or received.utcoffset() is None or received != stamp:
            raise ValueError('native quote clock differs from response receipt')
        vp = view.get("promotions")
        if not isinstance(vp, list) or len(vp) != len(promotions) or any(
                not isinstance(v, dict) or any(v.get(k) != p.get(k) for k in
                    ("promoId", "retailerPromotionId", "description", "type", "requiredProductQuantity"))
                for v, p in zip(vp, promotions)):
            raise ValueError("original native benefit view conflict")
    terms = {"source_condition_kind":"source_public_base_quote", "source_base_quote_only":True,
             "payable_price_unconfirmed":False, "source_quote_currency":"KRW",
             "source_base_price_role":"standalone_native_product_price",
             "source_promotion_declarations":deepcopy(promotions),
             "condition_text":raw.get("event_name"), "coupon_application_unconfirmed":bool(promotions),
             "source_benefit_application_unconfirmed":bool(promotions)}
    selections, coupons = [], []
    for promotion in promotions:
        facts = conditional_selection_facts_or_none(promotion["description"])
        required = promotion.get("requiredProductQuantity")
        if facts is not None:
            if type(required) is not int or required != facts["required_selection_quantity"]:
                raise ValueError("native selection count/literal conflict")
            selections.append(facts)
        elif required is not None:
            raise ValueError("unresolved native required quantity")
        match = re.fullmatch(r"(제타패스\s*X\s*.+?)\s+(\d+)만원 이상\s+(\d+)만원 할인", promotion["description"])
        if match:
            coupons.append({"displayCouponNm":promotion["description"], "purchaseMin":int(match[2])*10000,
                            "discount":int(match[3])*10000, "discountType":"source_won_declaration",
                            "source_program_name":match[1]})
    if selections:
        terms.update(source_selection_declarations=selections, selected_product_scope_unconfirmed=True)
        if len(selections) == 1:
            terms["source_required_product_quantity"] = selections[0]["required_selection_quantity"]
            if "conditional_discount_percent" in selections[0]:
                terms["conditional_discount_percent"] = selections[0]["conditional_discount_percent"]
    if coupons:
        terms.update(membership_eligibility_unconfirmed=True,
                     source_coupon_declarations={"couponInfo":None, "couponList":coupons})
    return {"source_base_quote": {"amount":amount, "currency":"KRW", **package,
                                 "observed_at":raw["crawled_at"], "source_view_sha256":_digest(node)},
            "source_promotions":deepcopy(promotions), "benefits_applied":False, "promotion_conditions":terms}
