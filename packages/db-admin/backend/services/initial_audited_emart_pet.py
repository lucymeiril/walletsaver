"""Exact pet forms from Emart's broad pet shelf."""

GROUPS = {
    "pet.food.treats.chew": (
        "이마트가 직접 수입한 치킨 화이트본 S 13개입", "반려견 골든 황태 채 70g",
        "몰리스 치킨랩츄 300g", "맥시 비프져키 800g",
    ),
    "pet.food.treats.meat": (
        "통통닭가슴살225g", "더독 치킨 치즈 슬라이스 100g", "통살가득 닭가슴살 20P", "담백순살닭가슴살210g",
    ),
    "pet.food.treats.cat_crunchy": ("템테이션 맛있는 닭고기맛 75g",),
    "pet.food.treats.cheese": ("몰리스 체다치즈볼 210g",),
    "pet.food.supplement.milk": ("서울우유 아이펫밀크 저지방 180ml",),
    "pet.food.feed.cat": ("위스카스 주니어 오션피쉬 1.1kg", "밥이보약 캣 NO스트레스 6.5kg"),
    "pet.food.feed.dog": (
        "시저 쇠고기와 참치 캔 3개입", "밥이보약 DOG 활기찬 노후 2kg", "시저 흰살생선과 야채 캔 3개입",
    ),
    "pet.cat.hygiene.litter": ("아메리칸솔루션 언씬티드 6.35kg",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_pet_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("반려동물",):
        return None
    return TITLES.get(evidence["source_title"])
