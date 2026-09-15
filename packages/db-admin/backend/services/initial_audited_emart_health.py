"""Exact product forms from Emart's broad health-food shelf."""

GROUPS = {
    "food.supplements.functional.calcium": ("칼슘듬뿍 튼튼키움 스틱젤리 280g",),
    "food.supplements.functional.zinc": ("아연듬뿍 면역키움 스틱젤리 280g",),
    "food.supplements.functional.probiotics": ("아이생각 키즈 생유산균", "락토핏 코어 2g*60포", "락토핏 골드(2g*50포)"),
    "food.supplements.functional.red_ginseng": (
        "한뿌리 홍삼대보 병 10입", "홍삼진황 50ml*20포", "홍삼원 골드(50ml*60포) 3000ml",
        "홍삼진본 40ml*20포", "6년근홍삼정업 2개입세트 (240g*2병) (쇼핑백동봉)",
    ),
    "food.supplements.functional.vitamin_c": ("[경남제약] 상큼한비타민레모나에스산90포(캐릭터 랜덤출고)", "비타민C 골드 플러스 120T"),
    "food.supplements.functional.lutein": ("[리얼닥터] 프리미엄 루테인13(500mg*30캡슐)", "루테인+비타민A 구미(4g*60개)"),
    "food.supplements.functional.omega3": ("프로메가 오메가3 트리플 654mg*60캡슐", "프로메가 알티지 오메가3 듀얼 520mg*60캡슐"),
    "food.supplements.functional.multivitamin": ("아임비타 멀티비타민 이뮨플러스7병", "멀티비타민 올인원 30정", "아임비타 멀티비타민 데일리 850mg x 60정"),
    "food.supplements.functional.biotin": ("비오틴+비타민B군 구미(3.5g*60개)",),
    "food.supplements.functional.collagen": ("휴럼 원데이 석류콜라겐젤리스틱(20g*28포)",),
    "food.supplements.protein.powder": (
        "프로틴쉐이크 초코맛", "프로틴쉐이크 곡물맛", "5K 프라이스 프로틴 쉐이크 딸기맛", "프로틴쉐이크 콘시리얼맛",
    ),
    "food.supplements.protein.drink": (
        "셀렉스 식물성 프로틴 당솔브 음료 오곡맛 190ml * 16입", "더단백 드링크 250ml*3입 (초코)",
        "더단백 프로틴 드링크 초코 250ml*18개입",
    ),
    "food.drinks.tea.ready": ("한뿌리 배도라지 병 10입",),
    "food.seasonings.syrups.honey": ("아카시아 벌꿀 500g", "[가보] 프리미엄 아카시아꿀 500g", "[동서식품] 아카시아 벌꿀 600g", "허니스틱 아카시아꿀(스틱형)"),
    "food.drinks.bases.lemon": ("[휴럼] NFC 유기농 레몬즙(20g*14포)",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_health_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("건강식품",):
        return None
    return TITLES.get(evidence["source_title"])
