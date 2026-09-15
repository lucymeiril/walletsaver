"""Exact reviewed forms in Costco's polluted cleaning shelf; no IO.

Merchandising context is evidence, not a category assignment. Mixed refill
titles may establish product type while independent quantity rules still hold
them. Unspecified powders, opaque brands, appliances and medical products are
not inferred. No fuzzy aliases are produced.
"""

from urllib.parse import urlparse

GROUPS = {
    "household.cleaning.laundry.liquid": (
        "프로쉬 알로에 베라 세탁세제 3L x 2",
        "액츠 프리미엄 젤 세탁세제 2.7L x 2 + 리필 1L x 4",
        "리큐 진한 겔에센스 세탁세제 4.5L",
        "프로쉬 석류 세탁세제 1.5L x 5",
        "슈가버블 친환경 세탁세제 내추럴버블 3L x 4",
        "퍼실 어드밴스드젤 세탁세제 4.0L x 2",
        "커클랜드 시그니춰 울트라 세탁세제 5.73L",
        "프로쉬 베이비 세탁세제 1.5L x 5",
        "리큐클린파워 세탁세제 리필 2L x 6(일반/드럼)",
        "프로쉬제로세탁세제1.5L x 2",
    ),
    "household.cleaning.laundry.capsule": ("슈가버블 원샷 캡슐세탁세제 50입 x3",),
    "household.cleaning.laundry.sheet": ("FIJI 시트형 세탁세제 120매",),
    "household.cleaning.laundry.powder": ("비트 분말 세탁세제 파우치 3kg x 2",),
    "household.cleaning.laundry.softener": (
        "다우니섬유유연제삶음탈취 4L", "다우니섬유유연제에이프릴후레쉬 5.03L",
    ),
    "household.cleaning.laundry.machine_cleaner": ("홈스타 세탁조 클리너 450ml x 8",),
    "household.cleaning.laundry.stain": ("넬리와우스틱얼룩제거용 76.5g x 3",),
    "household.cleaning.kitchen.detergent": (
        "무궁화키친솝주방세제4L + 700ml", "자연퐁뿌려쓰는주방세제750ml x 3",
    ),
    "household.cleaning.kitchen.produce_wash": ("슈가버블뿌리는과일& 야채세정제 500ml x 4",),
    "household.cleaning.general.multipurpose": ("미세스마이어스 다목적 세정제 750ml x 3 (리필 포함)",),
    "household.cleaning.general.deodorizer": ("페브리즈 항균 깨끗한향 섬유탈취제 920ml x 2 /최소구매2",),
    "household.kitchen.storage.bag": (
        "커클랜드 시그니춰 지퍼백 대형 32매 x 6", "커클랜드 시그니춰 지퍼백 중형 44매 x 6",
    ),
}
TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}

URL_ENTRIES = {
    "라브아실내건조캡슐세제 아이리스&피오니 60개": ("household.cleaning.laundry.capsule", "/LAVOIR-Capsule-Detergent-Iris-Peony-60-Pac/"),
    "파워브라이트캡슐세제 180 Pacs": ("household.cleaning.laundry.capsule", "/Powerbright-Capsule-Detergent-180-Pacs/"),
    "파워브라이트 초고농축 캡슐세제 180pc x 2": ("household.cleaning.laundry.capsule", "/PowerBright-Capsule-Detergent-180pc-x-2/"),
    "퍼실 디스크 캡슐세제 25g x 60pc": ("household.cleaning.laundry.capsule", "/Persil-Discs-Capsule-25g-x-60pc/"),
    "커클랜드 시그니춰 울트라 클린 팩세제 140팩": ("household.cleaning.laundry.capsule", "/Kirkland-Signature-Ultraclean-Pacs-140-Pacs/"),
    "퍼울머스크블룸 2L x 4": ("household.cleaning.laundry.liquid", "/Perwoll-Musk-Bloom-Detergent-2L-x-4/"),
    "FiJi 모락셀라스포츠 세제 3.5L x 2": ("household.cleaning.laundry.liquid", "/FiJi-Moraxella-Sports-Detergent-35L-x-2/"),
    "FiJi 디나자임딥클린맥스4.7L": ("household.cleaning.laundry.liquid", "/FiJi-Dnazyme-Deep-Clean-Max-47L/"),
    "액츠 데오후레쉬 3.5L x 2": ("household.cleaning.laundry.liquid", "/Actz-Deofresh-35L-x-2/"),
    "다우니 향기 부스터 화이트 티 840g": ("household.cleaning.laundry.scent_booster", "/Downy-Scent-Booster-White-Tea-840g/"),
}


def reviewed_costco_cleaning_leaf(evidence):
    if evidence["mart"] != "costco" or tuple(evidence["source_path_parts"]) != ("세제",):
        return None
    title = evidence["source_title"]
    entry = URL_ENTRIES.get(title)
    if entry:
        leaf, marker = entry
        if any(urlparse(url).hostname in {"costco.co.kr", "www.costco.co.kr"} and marker in urlparse(url).path for url in evidence.get("source_urls", ())):
            return leaf
    return TITLES.get(title)
