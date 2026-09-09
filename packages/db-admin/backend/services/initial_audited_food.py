"""Exact-title decisions from the pending Emart food shelves, September 2026.

These are classification proposals only, not identity merges or publication
approvals. Changed titles must be reviewed again; quantity checks are separate.
"""

AUDITED_EMART_FOOD_GROUPS = {
    "food.meals.noodles.cup_ramen": (
        "간짬뽕 큰컵 105g", "김치 왕뚜껑 110g", "라면 소컵 65g",
        "짬뽕 왕뚜껑 110g", "컵누들 매콤한맛 컵 (37.8GX6)",
    ),
    "food.meals.noodles.bag_ramen": (
        "농심 신라면툼바 137g*4개", "라면한그릇 건면 해물맛 94g*4개",
        "맛있는 라면 (115g*5입)", "불닭볶음면 (140gx5입)", "비빔면 130g*4입",
        "삼양라면 5입", "신라면 5입 600g (120gx5입)", "신라면 건면 5입",
        "신상 삼양 짜르르 140g*4개",
        "얼큰한 너구리 (120gx5입)", "오뚜기 부대찌개라면 130g*4개",
        "오징어 짬뽕 5입 620g (124g5입)", "올리브 짜파게티 (140gx5입)",
        "진라면 매운맛 (120GX5)", "진라면 순한맛 (120GX5)", "진라면 약간매운맛 120g*5개",
        "진비빔면 (156GX4)", "짜슐랭(145GX5)", "틈새라면 빨계떡120g*5입",
    ),
    "food.meals.noodles.pasta": (
        "[펠리체티] 유기농 통밀 푸질리 500g", "링귀니 500g", "스파게티 1kg",
        "스파게티 500g", "오뚜기 프레스코 토스카나 카사레체 500g", "통밀스파게티 450g",
    ),
    "food.meals.noodles.glass": ("당면 500g", "백설 햇당면 500g", "옛날자른당면300g", "햇당면300g"),
    "food.meals.noodles.sujebi": ("감자수제비800g(160g*5)",),
    "food.meals.noodles.udon": ("농심 코코이찌방야 카레우동 782g", "생생우동(253g/봉지)", "우동사리 1,150g"),
    "food.meals.noodles.jjolmyeon": ("[쓱7클럽] 새콤달콤생쫄면 920g(4인분)",),
    "food.meals.noodles.kalguksu": ("백설 생칼국수 550g",),
    "food.meals.noodles.tofu_noodle": ("지구식단 얇은두부면 100g",),
    "food.preserved.canned.tuna": ("고추참치150g", "담백한 살코기참치 90g", "살코기참치 150g"),
    "food.preserved.canned.corn": (
        "노슈가에디드 초당옥수수로 만든 스위트콘 340g", "스위트콘340g", "초당옥수수 스위트콘 340g",
    ),
    "food.preserved.canned.ham": ("리얼런천미트 340g", "스팸 클래식 200g*6입"),
    "food.produce.processed_vegetables.olive": ("슬라이스 블랙 올리브 235g", "피티드 블랙올리브 330g"),
    "food.meals.prepared.soup_stew": (
        "푸짐한 차돌짬뽕탕 500g", "고수의 맛집 금돼지식당 김치찌개 500g",
        "대림 정통모둠어묵탕 612g", "우리집 차돌된장찌개 500g", "정갈한 쇠고기무국 500g",
        "진한 사골곰탕 520g", "진한 육개장 500g", "진한삼계탕 880g",
        "푸짐한 소곱창전골 1kg", "NEW 송탄식 부대찌개 1.467kg",
    ),
    "food.meals.prepared.curry": (
        "1분 카레 130g", "3분 쇠고기 카레 200g", "3분 카레 매운맛 200g",
        "3분 카레 약간매운맛 200g", "3분카레 순한맛 200g",
    ),
    "food.meals.prepared.black_bean": ("3분 쇠고기 짜장 200g", "3분 짜장 200g"),
    "food.meals.prepared.pizza": ("[우주인피자] 불고기풀토핑 화덕피자_415g", "치즈딥 치즈 크러스트피자485g", "콘치즈 피자 300g"),
    "food.meals.prepared.pork_cutlet": ("맛있게 튀긴 등심돈까스 600g", "바삭바삭 돈까스 500g", "안심돈카츠 350g", "CJ 고메 통등심 돈카츠 300g"),
    "food.meals.prepared.chicken": ("크리스피 간장치킨 윙봉 400g",),
    "food.meals.prepared.meat_patty": ("동원 동그랑땡 710g", "CJ 도톰 동그랑땡795g"),
    "food.meals.prepared.tteokbokki": ("밀 국물떡볶이 416.2g", "X복순도가 마늘기름떡볶이 280g"),
    "food.meals.dumplings.assorted": ("갈비만두720g",),
    "food.meals.dumplings.boiled": ("물만두1,000g", "CJ 물만두370g*2"),
    "food.meals.dumplings.gyoza": ("CJ 왕교자1.12kg",),
    "food.meals.dumplings.dimsum": ("CJ 고메 새우하가우 135g",),
    "food.meals.rice.instant": ("우리쌀밥한공기 210g*12개", "잡곡밥 130g*6개", "햇반 100%통곡물밥 130g x 6번들", "CJ 햇반 100% 현미밥 130g*6개"),
    "food.meals.rice.fried": ("매콤통통 낙지볶음밥 500g (250g x 2개)", "탱글한 새우볶음밥 500g(250g x 2ea)", "통새우볶음밥1kg", "햇반 스팸김치볶음밥 440g"),
    "food.seafood.processed.fishcake": ("고래사어묵 모듬국탕어묵 432g", "꼬치어묵518g", "맛있는 부산어묵 사각어묵 400g(200g*2개입)", "한끼 네모어묵 150g"),
    "food.seafood.processed.surimi": ("맛있는 김밥용맛살 165g", "크라비 맛살 150g"),
    "food.meat.processed.smoked_duck": ("다향 훈제오리 (540g)",),
    "food.meat.processed.ham": ("슬라이스햄 60g", "잠봉 슬라이스 100g", "주부9단 김밥햄 170g*2"),
    "food.meat.processed.sausage": ("한입쏙쏙비엔나 550g", "ALL 비엔나 200g", "ALL 프랑크 200g", "BIG 주부9단 두툼프랑크 450g*2"),
    "food.bakery.bread.sliced": ("[쓱:싹] 밀도 쓱싹식빵_480g", "18겹 밀푀유 식빵 320G", "삼립 호두듬뿍 호밀식빵 385g", "소프트샌드위치식빵_380g", "아침미소 밀배아발효 토스트식빵 730g", "편안한유산균쌀식빵", "현미쌀식빵 330g"),
    "food.bakery.bread.roll": ("[기린] 고소한 옥수수 모닝롤 360g", "[쓱:싹] 밀도 허니모닝롤_180g (30gx6입)", "패밀리버터롤10입"),
    "food.bakery.bread.bagel": ("탕종베이글 블루베리 450g", "탕종베이글 어니언 450g", "탕종베이글 플레인 450g", "CJ 밸런스밀 고단백 저당 베이글 플레인 80g", "CJ 밸런스밀 고단백저당 베이글 에브리띵 80g", "CJ 밸런스밀 고단백저당 베이글 치즈 80g"),
    "food.bakery.bread.hard": ("[더베이커스테이블] 독일식 호밀 하드롤 240g", "유산균쌀바게트(6입)"),
    "food.bakery.bread.pastry": ("24결 버터 시나몬롤 페스츄리 79g", "더부드러운갈릭크로아상 40g", "베스트픽 페스츄리"),
    "food.bakery.bread.dough": ("미니 크로와상300g(생지)",),
    "food.bakery.dessert.cake": ("스윗초코롤케익", "치즈 크림 케익590g", "티라미수 180g"),
    "food.bakery.dessert.muffin": ("밀크앤허니 빅초코칩머핀 150g",),
    "food.bakery.dessert.scone": ("밀크앤허니 부드러운치즈스콘 85g",),
    "food.bakery.dessert.financier": ("허쉬초코퍼지휘낭시에 400g",),
    "food.bakery.spreads.fruit": ("[이마트 단독] 스머커스 텔레토비 기획팩 딸기프리저브 340g", "[이마트 단독] 스머커스x텔레토비 기획팩 오렌지마멀레이드 340g", "딸기잼 800g", "스머커스 딸기 프리저브 340g", "스머커스 오렌지 마멀레이드 340g", "스머커스 포도잼 340g", "LIGHT&JOY 당을줄인 청송사과쨈 290G"),
    "food.bakery.spreads.peanut": ("피넛버터 크런치 340g",),
    "food.meals.prepared.sandwich": ("[키친델리]크랜베리 치킨 샌드위치", "에그듬뿍 샌드위치 250g", "키친델리 단호박 리코타 샌드위치 273 g", "페퍼로니콤비치아바타샌드위치 510g", "BLT 샌드위치220g"),
}

AUDITED_EMART_FOOD_TITLES = {
    title: leaf for leaf, titles in AUDITED_EMART_FOOD_GROUPS.items() for title in titles
}
