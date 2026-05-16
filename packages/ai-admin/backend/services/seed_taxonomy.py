"""Conservative seed taxonomy used before DB-admin publishes public categories."""
from __future__ import annotations

import re
from typing import Any


SAFE_SEED_CATEGORY_IDS = frozenset(
    {
        # Classifier deterministic seed categories.
        "prepared_food.meal_kit.kimbap",
        "prepared_food.meal_kit",
        "prepared_food.deli.kimbap",
        "snack.nut",
        "snack.chip",
        "snack.chocolate",
        "snack.general",
        "dairy.milk.chocolate",
        "dairy.milk",
        "dairy.cheese",
        "dairy.yogurt",
        "livestock.egg",
        "meat.pork.belly",
        "meat.pork",
        "meat.beef",
        "meat.beef.hanwoo",
        "meat.chicken",
        "meat.chicken.breast",
        "seafood.fish",
        "seafood.frozen",
        "seafood.squid",
        "seafood.shrimp",
        "produce.fruit",
        "produce.vegetable",
        "grain.rice",
        "instant.noodle",
        "instant.rice",
        "beverage.water",
        "beverage.juice",
        "beverage.soda",
        "beverage.coffee",
        "beverage.general",
        "snack.ice_cream",
        "bakery.bread",
        "seafood.shellfish",
        "household.tissue",
        "household.storage",
        "household.cleaning",
        "household.bath",
        "household.kitchen",
        "household.general",
        "beauty.skincare",
        "beauty.haircare",
        "beauty.general",
        "fashion.clothing",
        "fashion.bag",
        "fashion.accessory",
        "electronics.mobile",
        "electronics.appliance",
        "electronics.general",
        "service.voucher",
        "service.ticket",
        "sports.general",
        "pet.general",
        "automotive.general",
        "retail.general",
        "processed.meat",
        "processed.sauce",
        "processed.spread",
        "processed.rice_cake",
        # Existing reviewed/legacy IDs used by the review pipeline tests and fixtures.
        "vegetable.cabbage",
        "processed.tofu.firm",
        "processed.sauce.ssamjang",
        "processed.meal.kimbap",
        "daily.detergent",
        "meat.beef.bulgogi",
        "meat.beef.soup_cut",
    }
)

SAFE_SEED_CATEGORY_LABELS = {
    "prepared_food.meal_kit.kimbap": "밀키트/델리/김밥",
    "prepared_food.meal_kit": "밀키트/델리",
    "prepared_food.deli.kimbap": "델리/김밥",
    "snack.nut": "간식/견과",
    "snack.chip": "간식/칩",
    "snack.chocolate": "간식/초콜릿",
    "snack.general": "간식/일반",
    "dairy.milk.chocolate": "유제품/초코우유",
    "dairy.milk": "유제품/우유",
    "dairy.cheese": "유제품/치즈",
    "dairy.yogurt": "유제품/요거트",
    "livestock.egg": "축산/계란",
    "meat.pork.belly": "축산/돼지고기/삼겹살",
    "meat.pork": "축산/돼지고기",
    "meat.beef": "축산/소고기",
    "meat.beef.hanwoo": "축산/한우",
    "meat.chicken": "축산/닭고기",
    "meat.chicken.breast": "축산/닭가슴살",
    "seafood.fish": "수산/생선",
    "seafood.frozen": "수산/냉동",
    "seafood.squid": "수산/오징어",
    "seafood.shrimp": "수산/새우",
    "produce.fruit": "농산/과일",
    "produce.vegetable": "농산/채소",
    "grain.rice": "곡류/쌀",
    "instant.noodle": "즉석/라면",
    "instant.rice": "즉석/밥",
    "beverage.water": "음료/생수",
    "beverage.juice": "음료/주스",
    "beverage.soda": "음료/탄산",
    "beverage.coffee": "음료/커피",
    "beverage.general": "음료/일반",
    "snack.ice_cream": "간식/아이스크림",
    "bakery.bread": "베이커리/빵",
    "seafood.shellfish": "수산/패류",
    "household.tissue": "생활용품/티슈",
    "household.storage": "생활용품/수납",
    "household.cleaning": "생활용품/청소",
    "household.bath": "생활용품/욕실",
    "household.kitchen": "생활용품/주방",
    "household.general": "생활용품/일반",
    "beauty.skincare": "뷰티/스킨케어",
    "beauty.haircare": "뷰티/헤어케어",
    "beauty.general": "뷰티/일반",
    "fashion.clothing": "패션/의류",
    "fashion.bag": "패션/가방",
    "fashion.accessory": "패션/잡화",
    "electronics.mobile": "가전/모바일",
    "electronics.appliance": "가전/생활가전",
    "electronics.general": "가전/일반",
    "service.voucher": "서비스/상품권",
    "service.ticket": "서비스/이용권",
    "sports.general": "스포츠/일반",
    "pet.general": "반려동물/일반",
    "automotive.general": "자동차용품/일반",
    "retail.general": "리테일/일반",
    "processed.meat": "가공식품/육가공",
    "processed.sauce": "가공식품/소스",
    "processed.spread": "가공식품/스프레드",
    "processed.rice_cake": "가공식품/떡",
    "vegetable.cabbage": "채소/양배추",
    "processed.tofu.firm": "가공식품/두부",
    "processed.sauce.ssamjang": "가공식품/소스/쌈장",
    "processed.meal.kimbap": "가공식품/김밥",
    "daily.detergent": "생활용품/세제",
    "meat.beef.bulgogi": "축산/소고기/불고기",
    "meat.beef.soup_cut": "축산/소고기/국거리",
}


SAFE_SEED_CATEGORY_ALIASES = {
    "두부": "processed.tofu.firm",
    "농산두부": "processed.tofu.firm",
    "농산물두부": "processed.tofu.firm",
    "agriculturetofu": "processed.tofu.firm",
    "agriculturebeantofu": "processed.tofu.firm",
    "식품두부": "processed.tofu.firm",
    "푸드두부": "processed.tofu.firm",
    "가공식품두부": "processed.tofu.firm",
    "processedtofu": "processed.tofu.firm",
    "processedsoytofu": "processed.tofu.firm",
    "soytofu": "processed.tofu.firm",
    "foodtofu": "processed.tofu.firm",
    "과일": "produce.fruit",
    "농산과일": "produce.fruit",
    "농산물과일": "produce.fruit",
    "agriculturefruit": "produce.fruit",
    "agriculturefruitapple": "produce.fruit",
    "fruitapple": "produce.fruit",
    "agriculturefruitcitrus": "produce.fruit",
    "fruittangerine": "produce.fruit",
    "fruitcitrus": "produce.fruit",
    "감귤": "produce.fruit",
    "귤": "produce.fruit",
    "오트밀": "grain.rice",
    "grainoatmeal": "grain.rice",
    "grainoat": "grain.rice",
    "pantrygrainoat": "grain.rice",
    "pantrygrainoatmeal": "grain.rice",
    "라면": "instant.noodle",
    "processednoodleramen": "instant.noodle",
    "noodleramen": "instant.noodle",
    "instantnoodleramen": "instant.noodle",
    "세탁세제": "daily.detergent",
    "detergent": "daily.detergent",
    "householddetergent": "daily.detergent",
    "householdlaundrydetergent": "daily.detergent",
    "밀키트델리": "prepared_food.meal_kit",
    "델리밀키트": "prepared_food.meal_kit",
    "밀키트": "prepared_food.meal_kit",
    "mealkit": "prepared_food.meal_kit",
    "preparedfoodmealkit": "prepared_food.meal_kit",
    "mealkitdeli": "prepared_food.meal_kit",
    "preparedfooddelimealkit": "prepared_food.meal_kit",
    "수산냉동": "seafood.frozen",
    "냉동수산": "seafood.frozen",
    "냉동해산물": "seafood.frozen",
    "해산물냉동": "seafood.frozen",
    "수산물냉동": "seafood.frozen",
    "seafoodfrozen": "seafood.frozen",
    "processedinstantmealkit": "prepared_food.meal_kit",
    "processedmealkit": "prepared_food.meal_kit",
    "snack": "snack.general",
    "processedsnack": "snack.general",
    "snacksnack": "snack.general",
    "snackchips": "snack.chip",
    "beverage": "beverage.general",
    "beveragecarbonated": "beverage.soda",
    "agricultureegg": "livestock.egg",
    "dairyegg": "livestock.egg",
    "livestockegg": "livestock.egg",
    "계란": "livestock.egg",
    "달걀": "livestock.egg",
    "bakerybread": "bakery.bread",
    "seafoodshellfish": "seafood.shellfish",
    "householdtissue": "household.tissue",
    "householdstorage": "household.storage",
    "livingstorage": "household.storage",
    "livingfurniturestorage": "household.storage",
    "householdcleaning": "household.cleaning",
    "cleaning": "household.cleaning",
    "bath": "household.bath",
    "bathroom": "household.bath",
    "kitchen": "household.kitchen",
    "beauty": "beauty.general",
    "cosmetics": "beauty.general",
    "skincare": "beauty.skincare",
    "haircare": "beauty.haircare",
    "fashion": "fashion.clothing",
    "apparel": "fashion.clothing",
    "clothing": "fashion.clothing",
    "bag": "fashion.bag",
    "luggage": "fashion.bag",
    "accessory": "fashion.accessory",
    "electronics": "electronics.general",
    "digital": "electronics.general",
    "mobile": "electronics.mobile",
    "phone": "electronics.mobile",
    "appliance": "electronics.appliance",
    "voucher": "service.voucher",
    "giftcard": "service.voucher",
    "ticket": "service.ticket",
    "sports": "sports.general",
    "pet": "pet.general",
    "automotive": "automotive.general",
    "retail": "retail.general",
    "generalmerchandise": "retail.general",
    "processedmeat": "processed.meat",
    "processedsauce": "processed.sauce",
    "processedspread": "processed.spread",
    "processeddairybutter": "processed.spread",
    "spread": "processed.spread",
    "butter": "processed.spread",
    "피넛버터": "processed.spread",
    "processedricecake": "processed.rice_cake",
    "processedgrainricecake": "processed.rice_cake",
    "ricecake": "processed.rice_cake",
    "떡": "processed.rice_cake",
    "agriculturefruitcherry": "produce.fruit",
    "agriculturefruitwatermelon": "produce.fruit",
    "agricultureleafycabbage": "vegetable.cabbage",
    "agriculturerootonion": "produce.vegetable",
    "agriculturevegetableasparagus": "produce.vegetable",
    "seafoodfishmackerel": "seafood.fish",
    "meatbeefprocessed": "meat.beef",
    "agriculturemushroom": "produce.vegetable",
    "vegetablemushroom": "produce.vegetable",
    "mushroom": "produce.vegetable",
    "dairycheese": "dairy.cheese",
    "beveragecoffee": "beverage.coffee",
    "instantporridge": "instant.rice",
    "processedsoup": "instant.rice",
}

_CATEGORY_TOKEN_RE = re.compile(r"[0-9a-z가-힣]+")


def _compact_category_alias(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return "".join(ch for ch in raw if ch.isalnum() or "가" <= ch <= "힣")


LABEL_DERIVED_CATEGORY_ALIASES = {
    _compact_category_alias(label): category_id
    for category_id, label in SAFE_SEED_CATEGORY_LABELS.items()
}

SAFE_SEED_CATEGORY_FAMILY_RULES = (
    {
        "target": "produce.fruit",
        "required_any": {"fruit", "과일"},
        "source_any": {"agriculture", "produce", "fruit", "농산", "농산물"},
        "blocked_any": {"snack", "confectionery", "candy", "jelly", "beverage", "음료"},
    },
    {
        "target": "produce.vegetable",
        "required_any": {"vegetable", "root", "leafy", "채소", "야채"},
        "source_any": {"agriculture", "produce", "vegetable", "root", "leafy", "농산", "농산물"},
        "blocked_any": {"snack", "beverage", "음료"},
    },
    {
        "target": "seafood.fish",
        "required_any": {"fish", "생선"},
        "source_any": {"seafood", "marine", "fish", "수산", "수산물"},
        "blocked_any": {"snack", "confectionery"},
    },
    {
        "target": "seafood.frozen",
        "required_any": {"frozen", "냉동"},
        "source_any": {"seafood", "marine", "fish", "수산", "수산물"},
        "blocked_any": {"snack", "confectionery"},
    },
    {
        "target": "meat.beef",
        "required_any": {"beef", "소고기", "쇠고기"},
        "source_any": {"meat", "beef", "축산"},
        "blocked_any": {"snack"},
    },
    {
        "target": "meat.pork",
        "required_any": {"pork", "돼지고기"},
        "source_any": {"meat", "pork", "축산"},
        "blocked_any": {"snack"},
    },
    {
        "target": "meat.chicken",
        "required_any": {"chicken", "닭고기"},
        "source_any": {"meat", "chicken", "축산"},
        "blocked_any": {"snack"},
    },
    {
        "target": "daily.detergent",
        "required_any": {"detergent", "laundry", "세제"},
        "source_any": {"household", "daily", "laundry", "생활용품"},
        "blocked_any": set(),
    },
    {
        "target": "instant.noodle",
        "required_any": {"noodle", "ramen", "라면"},
        "source_any": {"processed", "instant", "noodle", "식품"},
        "blocked_any": set(),
    },
    {
        "target": "prepared_food.meal_kit",
        "required_any": {"mealkit", "meal_kit", "밀키트"},
        "source_any": {"prepared", "prepared_food", "processed", "instant", "deli", "식품"},
        "blocked_any": set(),
    },
    {
        "target": "electronics.mobile",
        "required_any": {"mobile", "phone", "smartphone", "cellphone", "모바일", "휴대폰", "스마트폰"},
        "source_any": {"electronics", "digital", "mobile", "phone", "가전", "디지털"},
        "blocked_any": set(),
    },
    {
        "target": "electronics.appliance",
        "required_any": {"appliance", "가전", "냉장고", "세탁기", "선풍기"},
        "source_any": {"electronics", "appliance", "home", "가전"},
        "blocked_any": set(),
    },
    {
        "target": "fashion.clothing",
        "required_any": {"fashion", "apparel", "clothing", "의류", "패션"},
        "source_any": {"fashion", "apparel", "clothing", "sports", "패션"},
        "blocked_any": set(),
    },
    {
        "target": "fashion.bag",
        "required_any": {"bag", "luggage", "가방", "캐리어"},
        "source_any": {"fashion", "travel", "bag", "패션", "여행"},
        "blocked_any": set(),
    },
    {
        "target": "beauty.general",
        "required_any": {"beauty", "cosmetics", "뷰티", "화장품"},
        "source_any": {"beauty", "cosmetics", "뷰티"},
        "blocked_any": set(),
    },
    {
        "target": "household.general",
        "required_any": {"household", "living", "생활용품", "생활"},
        "source_any": {"household", "living", "home", "생활용품"},
        "blocked_any": set(),
    },
    {
        "target": "service.voucher",
        "required_any": {"voucher", "giftcard", "coupon", "상품권", "기프트카드", "금액권"},
        "source_any": {"service", "voucher", "ticket", "서비스"},
        "blocked_any": set(),
    },
)

PROMPT_CATEGORY_HINT_IDS = (
    "prepared_food.meal_kit.kimbap",
    "seafood.frozen",
    "produce.fruit",
    "processed.tofu.firm",
    "snack.general",
    "instant.noodle",
    "household.storage",
    "household.general",
    "electronics.mobile",
    "electronics.appliance",
    "fashion.clothing",
    "beauty.general",
    "service.voucher",
    "retail.general",
    "processed.spread",
    "processed.rice_cake",
)


def normalize_category_id(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in SAFE_SEED_CATEGORY_IDS:
        return raw
    compact = _compact_category_alias(raw)
    return (
        SAFE_SEED_CATEGORY_ALIASES.get(compact)
        or LABEL_DERIVED_CATEGORY_ALIASES.get(compact)
        or _family_parent_category(raw)
        or raw
    )


def _category_tokens(raw: str) -> set[str]:
    return set(_CATEGORY_TOKEN_RE.findall(raw))


def _family_parent_category(raw: str) -> str | None:
    tokens = _category_tokens(raw)
    if not tokens:
        return None
    for rule in SAFE_SEED_CATEGORY_FAMILY_RULES:
        required = rule["required_any"]
        sources = rule["source_any"]
        blocked = rule["blocked_any"]
        if tokens & blocked:
            continue
        if not tokens & required:
            continue
        if tokens & sources or raw.split(".", 1)[0] in required:
            return str(rule["target"])
    return None


def taxonomy_alias_overfit_metrics() -> dict[str, Any]:
    exact_alias_count = len(SAFE_SEED_CATEGORY_ALIASES)
    family_rule_count = len(SAFE_SEED_CATEGORY_FAMILY_RULES)
    return {
        "exact_alias_count": exact_alias_count,
        "family_rule_count": family_rule_count,
        "exact_aliases_per_family_rule": round(exact_alias_count / max(family_rule_count, 1), 2),
        "risk": "warn" if exact_alias_count > family_rule_count * 5 else "ok",
    }


def get_category_display_label(value: Any) -> str:
    category_id = normalize_category_id(value)
    return SAFE_SEED_CATEGORY_LABELS.get(category_id, category_id)


def is_safe_seed_category(value: Any) -> bool:
    return normalize_category_id(value) in SAFE_SEED_CATEGORY_IDS


def seed_taxonomy_prompt_line() -> str:
    categories = ", ".join(PROMPT_CATEGORY_HINT_IDS)
    return (
        "Official category_id hints: "
        f"{categories}"
    )
