"""
WalletSavior 자동완성 키워드 시스템.

500 개 이상의 키워드, 동의어 매핑, 인기 검색 패턴을 제공합니다.
"""

from __future__ import annotations
from typing import Optional


# ──────────────────────────────────────────────
# 키워드 데이터
# word, synonyms, category_id, search_count
# ──────────────────────────────────────────────

def _kw(word: str, *, synonyms: Optional[list[str]] = None,
        category_id: Optional[str] = None, search_count: int = 0) -> dict:
    return {
        "word": word,
        "synonyms": synonyms or [],
        "category_id": category_id,
        "search_count": search_count,
        "is_active": True,
    }


KEYWORDS: list[dict] = [
    # ═══════════════════════════════════════
    # 농산물 — 엽채류
    # ═══════════════════════════════════════
    _kw("배추", synonyms=["김장배추", "알배추", "절임배추"], category_id="agriculture.leafy.napa_cabbage", search_count=850),
    _kw("시금치", synonyms=["포항초", "시금치나물"], category_id="agriculture.leafy.spinach", search_count=620),
    _kw("상추", synonyms=["청상추", "적상추", "로메인"], category_id="agriculture.leafy.lettuce", search_count=480),
    _kw("양배추", synonyms=["캐비지", "적양배추"], category_id="agriculture.leafy.cabbage", search_count=520),
    _kw("깻잎", synonyms=["들깻잎", "깻잎장아찌"], category_id="agriculture.leafy.perilla", search_count=390),
    _kw("부추", synonyms=["정구지", "솔"], category_id="agriculture.leafy.chive", search_count=310),
    _kw("미나리", synonyms=["돌미나리"], category_id="agriculture.leafy.water_parsley", search_count=280),
    _kw("청경채", category_id="agriculture.leafy.bok_choy", search_count=190),
    _kw("케일", category_id="agriculture.leafy.kale", search_count=170),
    _kw("콩나물", synonyms=["콩나물국"], category_id="agriculture.leafy.bean_sprout", search_count=650),
    _kw("숙주나물", synonyms=["숙주"], category_id="agriculture.leafy.mung_sprout", search_count=320),
    _kw("대파", synonyms=["파", "쪽파"], category_id="agriculture.leafy.green_onion", search_count=780),

    # 과채류
    _kw("토마토", synonyms=["방울토마토", "대추토마토", "완숙토마토"], category_id="agriculture.fruit_veg.tomato", search_count=720),
    _kw("오이", synonyms=["백오이", "취청오이", "가시오이"], category_id="agriculture.fruit_veg.cucumber", search_count=510),
    _kw("고추", synonyms=["풋고추", "청양고추", "홍고추"], category_id="agriculture.fruit_veg.chili", search_count=580),
    _kw("파프리카", synonyms=["빨간파프리카", "노란파프리카"], category_id="agriculture.fruit_veg.paprika", search_count=340),
    _kw("가지", category_id="agriculture.fruit_veg.eggplant", search_count=230),
    _kw("호박", synonyms=["늙은호박", "단호박", "애호박"], category_id="agriculture.fruit_veg.pumpkin", search_count=450),
    _kw("옥수수", synonyms=["찰옥수수", "초당옥수수"], category_id="agriculture.fruit_veg.corn", search_count=380),

    # 근채류
    _kw("감자", synonyms=["수미감자", "홍감자", "알감자"], category_id="agriculture.root.potato", search_count=680),
    _kw("고구마", synonyms=["밤고구마", "호박고구마", "꿀고구마"], category_id="agriculture.root.sweet_potato", search_count=720),
    _kw("당근", category_id="agriculture.root.carrot", search_count=450),
    _kw("무", synonyms=["조선무", "총각무", "열무"], category_id="agriculture.root.radish", search_count=520),
    _kw("양파", synonyms=["자색양파", "백양파"], category_id="agriculture.root.onion", search_count=880),
    _kw("마늘", synonyms=["다진마늘", "깐마늘", "통마늘"], category_id="agriculture.root.garlic", search_count=760),
    _kw("생강", synonyms=["다진생강"], category_id="agriculture.root.ginger", search_count=340),

    # 과일류
    _kw("사과", synonyms=["부사", "홍로", "아오리"], category_id="agriculture.fruit.apple", search_count=920),
    _kw("배", synonyms=["신고배", "원황배"], category_id="agriculture.fruit.pear", search_count=580),
    _kw("감귤", synonyms=["귤", "제주감귤", "밀감"], category_id="agriculture.fruit.tangerine", search_count=750),
    _kw("딸기", synonyms=["설향", "죽향", "킹스베리"], category_id="agriculture.fruit.strawberry", search_count=890),
    _kw("포도", synonyms=["캠벨", "거봉", "샤인머스캣"], category_id="agriculture.fruit.grape", search_count=670),
    _kw("수박", synonyms=["애플수박", "미니수박"], category_id="agriculture.fruit.watermelon", search_count=620),
    _kw("참외", category_id="agriculture.fruit.melon", search_count=430),
    _kw("복숭아", synonyms=["황도", "백도", "천도복숭아"], category_id="agriculture.fruit.peach", search_count=540),
    _kw("자두", category_id="agriculture.fruit.plum", search_count=280),
    _kw("망고", synonyms=["애플망고"], category_id="agriculture.fruit.mango", search_count=460),
    _kw("바나나", synonyms=["스위티오", "델몬트바나나"], category_id="agriculture.fruit.banana", search_count=780),
    _kw("키위", synonyms=["골드키위", "그린키위"], category_id="agriculture.fruit.kiwi", search_count=390),
    _kw("블루베리", category_id="agriculture.fruit.blueberry", search_count=420),
    _kw("체리", category_id="agriculture.fruit.cherry", search_count=350),
    _kw("파인애플", category_id="agriculture.fruit.pineapple", search_count=310),
    _kw("한라봉", synonyms=["천혜향", "레드향"], category_id="agriculture.fruit.hallabong", search_count=480),
    _kw("레몬", category_id="agriculture.fruit.lemon", search_count=290),
    _kw("샤인머스캣", synonyms=["샤머", "머스캣"], category_id="agriculture.fruit.shine_muscat", search_count=810),

    # 버섯류
    _kw("새송이버섯", synonyms=["새송이"], category_id="agriculture.mushroom.king_oyster", search_count=380),
    _kw("팽이버섯", synonyms=["팽이"], category_id="agriculture.mushroom.enoki", search_count=350),
    _kw("표고버섯", synonyms=["표고"], category_id="agriculture.mushroom.shiitake", search_count=310),

    # 곡류
    _kw("쌀", synonyms=["백미", "현미", "잡곡"], category_id="agriculture.grain.rice", search_count=950),
    _kw("찹쌀", category_id="agriculture.grain.glutinous_rice", search_count=280),

    # ═══════════════════════════════════════
    # 축산물
    # ═══════════════════════════════════════
    _kw("삼겹살", synonyms=["돼지고기", "삼겹", "목살", "구이용삼겹살"], category_id="livestock.pork.belly", search_count=1200),
    _kw("목살", synonyms=["돼지목살", "목심"], category_id="livestock.pork.neck", search_count=650),
    _kw("앞다리살", synonyms=["앞다리", "전지"], category_id="livestock.pork.front_leg", search_count=380),
    _kw("돼지갈비", synonyms=["갈비", "양념갈비"], category_id="livestock.pork.ribs", search_count=520),
    _kw("등심", synonyms=["소등심", "꽃등심"], category_id="livestock.beef.sirloin", search_count=680),
    _kw("안심", synonyms=["소안심"], category_id="livestock.beef.tenderloin", search_count=450),
    _kw("소갈비", synonyms=["LA갈비", "꽃갈비", "찜갈비"], category_id="livestock.beef.ribs", search_count=780),
    _kw("차돌박이", synonyms=["차돌"], category_id="livestock.beef.chadol", search_count=580),
    _kw("한우", synonyms=["국내산소고기", "한우등심", "한우갈비"], category_id="livestock.beef.hanwoo", search_count=920),
    _kw("양지", synonyms=["사골", "양지머리"], category_id="livestock.beef.brisket", search_count=380),
    _kw("통닭", synonyms=["생닭", "닭한마리"], category_id="livestock.chicken.whole", search_count=520),
    _kw("닭가슴살", synonyms=["닭가슴", "닭가슴살스테이크"], category_id="livestock.chicken.breast", search_count=680),
    _kw("닭다리", synonyms=["닭다리살", "닭봉"], category_id="livestock.chicken.leg", search_count=420),
    _kw("닭날개", synonyms=["윙", "닭봉"], category_id="livestock.chicken.wing", search_count=310),
    _kw("계란", synonyms=["달걀", "에그", "egg", "유정란"], category_id="livestock.egg", search_count=1100),
    _kw("오리고기", synonyms=["오리", "훈제오리"], category_id="livestock.duck", search_count=280),
    _kw("메추리알", category_id="livestock.quail_egg", search_count=180),

    # ═══════════════════════════════════════
    # 수산물
    # ═══════════════════════════════════════
    _kw("고등어", synonyms=["자반고등어", "노르웨이고등어"], category_id="seafood.fish.mackerel", search_count=580),
    _kw("삼치", category_id="seafood.fish.spanish_mackerel", search_count=320),
    _kw("갈치", synonyms=["은갈치", "먹갈치"], category_id="seafood.fish.cutlass", search_count=450),
    _kw("연어", synonyms=["훈제연어", "연어회", "사시미"], category_id="seafood.fish.salmon", search_count=680),
    _kw("참치", synonyms=["참치회", "다랑어"], category_id="seafood.fish.tuna", search_count=550),
    _kw("광어", synonyms=["광어회", "넙치"], category_id="seafood.fish.flounder", search_count=420),
    _kw("새우", synonyms=["대하", "흰다리새우", "왕새우"], category_id="seafood.crustacean.shrimp", search_count=620),
    _kw("꽃게", synonyms=["암꽃게"], category_id="seafood.crustacean.blue_crab", search_count=480),
    _kw("대게", synonyms=["영덕대게", "홍게"], category_id="seafood.crustacean.snow_crab", search_count=410),
    _kw("랍스터", synonyms=["lobster"], category_id="seafood.crustacean.lobster", search_count=280),
    _kw("바지락", category_id="seafood.shellfish.clam", search_count=350),
    _kw("전복", synonyms=["활전복", "완도전복"], category_id="seafood.shellfish.abalone", search_count=420),
    _kw("굴", synonyms=["석화", "생굴", "통영굴"], category_id="seafood.shellfish.oyster", search_count=380),
    _kw("오징어", synonyms=["생오징어", "냉동오징어"], category_id="seafood.shellfish.squid", search_count=480),
    _kw("낙지", synonyms=["세발낙지", "산낙지"], category_id="seafood.shellfish.octopus", search_count=310),
    _kw("김", synonyms=["구운김", "조미김", "돌김"], category_id="seafood.seaweed.laver", search_count=720),
    _kw("미역", synonyms=["건미역", "완도미역"], category_id="seafood.seaweed.wakame", search_count=480),
    _kw("다시마", synonyms=["건다시마"], category_id="seafood.seaweed.kelp", search_count=310),
    _kw("멸치", synonyms=["국물용멸치", "볶음멸치"], category_id="seafood.dried.anchovy", search_count=520),
    _kw("새우젓", category_id="seafood.fermented.shrimp_paste", search_count=280),

    # ═══════════════════════════════════════
    # 가공식품
    # ═══════════════════════════════════════
    _kw("라면", synonyms=["신라면", "진라면", "불닭볶음면", "너구리", "안성탕면"], category_id="processed.noodle.ramen", search_count=1350),
    _kw("신라면", synonyms=["농심신라면", "신라면블랙"], category_id="processed.noodle.ramen", search_count=980),
    _kw("진라면", synonyms=["오뚜기진라면"], category_id="processed.noodle.ramen", search_count=650),
    _kw("불닭볶음면", synonyms=["불닭", "삼양불닭"], category_id="processed.noodle.ramen", search_count=720),
    _kw("국수", synonyms=["소면", "중면", "칼국수면"], category_id="processed.noodle.noodle", search_count=380),
    _kw("파스타", synonyms=["스파게티", "펜네"], category_id="processed.noodle.pasta", search_count=350),
    _kw("당면", category_id="processed.noodle.glass_noodle", search_count=280),
    _kw("참치캔", synonyms=["동원참치", "사조참치"], category_id="processed.canned.tuna", search_count=620),
    _kw("햄", synonyms=["구슬함박", "비엔나소시지"], category_id="processed.canned.ham", search_count=450),
    _kw("스팸", synonyms=["스팸클래식", "SPAM"], category_id="processed.canned.spam", search_count=780),
    _kw("만두", synonyms=["비비고만두", "교자만두", "물만두", "군만두"], category_id="processed.frozen.dumpling", search_count=680),
    _kw("냉동피자", synonyms=["오뚜기피자", "피자"], category_id="processed.frozen.pizza", search_count=350),
    _kw("아이스크림", synonyms=["빙그레", "하겐다즈", "바닐라"], category_id="processed.frozen.ice_cream", search_count=520),
    _kw("간장", synonyms=["진간장", "양조간장", "국간장"], category_id="processed.sauce.soy_sauce", search_count=580),
    _kw("된장", synonyms=["재래된장", "쌈장"], category_id="processed.sauce.doenjang", search_count=420),
    _kw("고추장", synonyms=["태양초고추장", "찰고추장"], category_id="processed.sauce.gochujang", search_count=480),
    _kw("케첩", synonyms=["오뚜기케첩", "하인즈케첩"], category_id="processed.sauce.ketchup", search_count=280),
    _kw("마요네즈", synonyms=["마요", "오뚜기마요"], category_id="processed.sauce.mayo", search_count=310),
    _kw("설탕", synonyms=["백설탕", "흑설탕"], category_id="processed.sauce.sugar", search_count=350),
    _kw("소금", synonyms=["천일염", "꽃소금"], category_id="processed.sauce.salt", search_count=380),
    _kw("식용유", synonyms=["콩기름", "해바라기유"], category_id="processed.oil.vegetable", search_count=420),
    _kw("올리브유", synonyms=["올리브오일", "엑스트라버진"], category_id="processed.oil.olive", search_count=380),
    _kw("참기름", synonyms=["방앗간참기름"], category_id="processed.oil.sesame", search_count=480),
    _kw("들기름", category_id="processed.oil.perilla", search_count=350),
    _kw("밀가루", synonyms=["강력분", "중력분", "박력분"], category_id="processed.flour.wheat", search_count=380),
    _kw("부침가루", synonyms=["백설부침가루"], category_id="processed.flour.pancake", search_count=310),
    _kw("즉석밥", synonyms=["햇반", "오뚜기밥"], category_id="processed.instant.rice", search_count=580),
    _kw("밀키트", synonyms=["쿠킹박스", "간편요리"], category_id="processed.instant.meal_kit", search_count=420),
    _kw("김치", synonyms=["포기김치", "맛김치", "총각김치"], category_id="processed.side.kimchi", search_count=820),
    _kw("두부", synonyms=["풀무원두부", "CJ두부"], category_id="processed.tofu.firm", search_count=520),
    _kw("식빵", synonyms=["토스트", "삼립식빵"], category_id="processed.bakery.bread", search_count=380),

    # ═══════════════════════════════════════
    # 생활용품
    # ═══════════════════════════════════════
    _kw("세탁세제", synonyms=["액체세제", "가루세제", "퍼실", "피지"], category_id="household.detergent.laundry", search_count=450),
    _kw("섬유유연제", synonyms=["다우니", "피죤", "스너글"], category_id="household.detergent.softener", search_count=380),
    _kw("주방세제", synonyms=["퐁퐁", "자연퐁", "주방세정제"], category_id="household.detergent.dish", search_count=310),
    _kw("화장지", synonyms=["휴지", "두루마리화장지", "티슈"], category_id="household.tissue.toilet", search_count=580),
    _kw("키친타월", synonyms=["키친타올", "키친페이퍼"], category_id="household.tissue.kitchen", search_count=280),
    _kw("물티슈", synonyms=["아기물티슈", "캡형물티슈"], category_id="household.tissue.wet", search_count=420),
    _kw("쓰레기봉투", synonyms=["종량제봉투"], category_id="household.bag.trash", search_count=310),
    _kw("치약", synonyms=["메디안", "2080", "죽염치약"], category_id="household.bathroom.toothpaste", search_count=350),
    _kw("칫솔", synonyms=["전동칫솔", "오랄비"], category_id="household.bathroom.toothbrush", search_count=310),
    _kw("바디워시", synonyms=["샤워젤", "도브바디워시"], category_id="household.bathroom.body_wash", search_count=350),
    _kw("샴푸", synonyms=["려샴푸", "팬틴", "헤드앤숄더"], category_id="household.bathroom.shampoo", search_count=420),

    # ═══════════════════════════════════════
    # 음료
    # ═══════════════════════════════════════
    _kw("생수", synonyms=["삼다수", "아이시스", "백산수", "물"], category_id="beverage.water.still", search_count=780),
    _kw("탄산수", synonyms=["트레비", "씨그램", "페리에"], category_id="beverage.water.sparkling", search_count=380),
    _kw("콜라", synonyms=["코카콜라", "펩시콜라", "제로콜라"], category_id="beverage.soda.cola", search_count=650),
    _kw("사이다", synonyms=["칠성사이다", "스프라이트", "제로사이다"], category_id="beverage.soda.cider", search_count=480),
    _kw("오렌지주스", synonyms=["미닛메이드", "델몬트"], category_id="beverage.juice.orange", search_count=350),
    _kw("원두커피", synonyms=["커피원두", "홀빈"], category_id="beverage.coffee.bean", search_count=450),
    _kw("커피믹스", synonyms=["맥심", "동서커피믹스", "카누"], category_id="beverage.coffee.mix", search_count=580),
    _kw("캡슐커피", synonyms=["네스프레소", "돌체구스토"], category_id="beverage.coffee.capsule", search_count=350),
    _kw("녹차", synonyms=["설록차", "현미녹차"], category_id="beverage.tea.green", search_count=310),
    _kw("보리차", synonyms=["티백보리차"], category_id="beverage.tea.barley", search_count=280),

    # ═══════════════════════════════════════
    # 유제품
    # ═══════════════════════════════════════
    _kw("우유", synonyms=["milk", "흰우유", "서울우유", "매일우유", "남양유업"], category_id="dairy.milk.plain", search_count=880),
    _kw("초코우유", synonyms=["서울우유초코", "초코"], category_id="dairy.milk.chocolate", search_count=350),
    _kw("딸기우유", synonyms=["서울우유딸기"], category_id="dairy.milk.strawberry", search_count=310),
    _kw("바나나우유", synonyms=["빙그레바나나우유", "바나나맛우유"], category_id="dairy.milk.banana", search_count=480),
    _kw("요거트", synonyms=["요플레", "액티비아"], category_id="dairy.yogurt.cup", search_count=380),
    _kw("그릭요거트", synonyms=["그릭"], category_id="dairy.yogurt.greek", search_count=310),
    _kw("치즈", synonyms=["슬라이스치즈", "cheese"], category_id="dairy.cheese.slice", search_count=450),
    _kw("모짜렐라", synonyms=["모짜렐라치즈", "피자치즈"], category_id="dairy.cheese.mozzarella", search_count=350),
    _kw("크림치즈", synonyms=["필라델피아크림치즈"], category_id="dairy.cheese.cream", search_count=280),
    _kw("버터", synonyms=["무염버터", "가염버터"], category_id="dairy.butter.butter", search_count=380),

    # ═══════════════════════════════════════
    # 주류
    # ═══════════════════════════════════════
    _kw("맥주", synonyms=["beer", "카스", "하이트", "테라"], category_id="alcohol.beer.domestic", search_count=680),
    _kw("수입맥주", synonyms=["하이네켄", "칭따오", "아사히", "기네스"], category_id="alcohol.beer.imported", search_count=450),
    _kw("소주", synonyms=["참이슬", "처음처럼", "진로"], category_id="alcohol.soju", search_count=750),
    _kw("와인", synonyms=["wine", "레드와인", "화이트와인"], category_id="alcohol.wine", search_count=480),
    _kw("위스키", synonyms=["whisky", "잭다니엘", "조니워커"], category_id="alcohol.whisky", search_count=310),
    _kw("막걸리", synonyms=["장수막걸리", "국순당"], category_id="alcohol.makgeolli", search_count=350),

    # ═══════════════════════════════════════
    # 건강식품
    # ═══════════════════════════════════════
    _kw("비타민C", synonyms=["비타민씨", "고려은단비타민C"], category_id="health.vitamin.c", search_count=520),
    _kw("종합비타민", synonyms=["멀티비타민", "센트룸"], category_id="health.vitamin.multi", search_count=450),
    _kw("유산균", synonyms=["프로바이오틱스", "락토핏"], category_id="health.probiotic", search_count=480),
    _kw("홍삼", synonyms=["정관장", "홍삼액", "홍삼정"], category_id="health.ginseng", search_count=580),
    _kw("오메가3", synonyms=["크릴오일", "EPA", "DHA"], category_id="health.omega", search_count=380),
    _kw("프로틴", synonyms=["단백질쉐이크", "단백질보충제"], category_id="health.protein", search_count=350),
    _kw("콜라겐", synonyms=["피쉬콜라겐"], category_id="health.collagen", search_count=310),

    # ═══════════════════════════════════════
    # 간식
    # ═══════════════════════════════════════
    _kw("감자칩", synonyms=["포테이토칩", "프링글스", "레이즈"], category_id="snack.chip.potato", search_count=420),
    _kw("새우깡", synonyms=["농심새우깡"], category_id="snack.chip.shrimp", search_count=350),
    _kw("초코파이", synonyms=["오리온초코파이"], category_id="snack.chip.choco_pie", search_count=380),
    _kw("빼빼로", synonyms=["롯데빼빼로"], category_id="snack.chip.pepero", search_count=350),
    _kw("초콜릿", synonyms=["가나초콜릿", "페레로로쉐", "린트"], category_id="snack.chocolate", search_count=420),
    _kw("젤리", synonyms=["하리보", "마이구미", "곰젤리"], category_id="snack.candy.jelly", search_count=310),
    _kw("아몬드", synonyms=["구운아몬드", "허니버터아몬드"], category_id="snack.nut.almond", search_count=380),
    _kw("믹스넛", synonyms=["견과류세트", "너트류"], category_id="snack.nut.mix", search_count=420),

    # ═══════════════════════════════════════
    # 주유소
    # ═══════════════════════════════════════
    _kw("휘발유", synonyms=["가솔린", "기름값", "주유"], category_id="gas.gasoline", search_count=750),
    _kw("경유", synonyms=["디젤", "diesel"], category_id="gas.diesel", search_count=480),
    _kw("LPG", synonyms=["엘피지", "가스"], category_id="gas.lpg", search_count=310),

    # ═══════════════════════════════════════
    # 식당
    # ═══════════════════════════════════════
    _kw("한식", synonyms=["한정식", "백반", "가정식"], category_id="restaurant.korean", search_count=520),
    _kw("중식", synonyms=["중국음식", "짜장면", "짬뽕"], category_id="restaurant.chinese", search_count=480),
    _kw("일식", synonyms=["초밥", "라멘", "돈카츠"], category_id="restaurant.japanese", search_count=450),
    _kw("양식", synonyms=["파스타레스토랑", "스테이크"], category_id="restaurant.western", search_count=380),
    _kw("분식", synonyms=["떡볶이", "김밥", "라볶이"], category_id="restaurant.snack_bar", search_count=520),
    _kw("패스트푸드", synonyms=["맥도날드", "버거킹", "KFC"], category_id="restaurant.fastfood", search_count=450),
    _kw("카페", synonyms=["스타벅스", "이디야", "투썸플레이스", "커피숍"], category_id="restaurant.cafe", search_count=680),

    # ═══════════════════════════════════════
    # 배달
    # ═══════════════════════════════════════
    _kw("치킨", synonyms=["배달치킨", "BBQ치킨", "교촌치킨", "BHC"], category_id="delivery.chicken", search_count=950),
    _kw("피자", synonyms=["도미노피자", "피자헛", "파파존스"], category_id="delivery.pizza", search_count=720),
    _kw("족발", synonyms=["족발배달", "보쌈", "장충동족발"], category_id="delivery.jokbal", search_count=480),

    # ═══════════════════════════════════════
    # 의류
    # ═══════════════════════════════════════
    _kw("운동화", synonyms=["나이키", "아디다스", "뉴발란스"], category_id="clothing.shoes.sneakers", search_count=580),
    _kw("원피스", synonyms=["여성원피스", "롱원피스"], category_id="clothing.women.dress", search_count=420),
    _kw("백팩", synonyms=["가방", "배낭"], category_id="clothing.bag.backpack", search_count=380),
    _kw("양말", synonyms=["남성양말", "여성양말", "스포츠양말"], category_id="clothing.underwear.socks", search_count=310),

    # ═══════════════════════════════════════
    # 가전/디지털
    # ═══════════════════════════════════════
    _kw("냉장고", synonyms=["삼성냉장고", "LG냉장고", "비스포크"], category_id="appliance.kitchen.fridge", search_count=520),
    _kw("에어프라이어", synonyms=["에어프라이기"], category_id="appliance.kitchen.airfryer", search_count=480),
    _kw("세탁기", synonyms=["LG세탁기", "삼성세탁기", "드럼세탁기"], category_id="appliance.living.washer", search_count=450),
    _kw("에어컨", synonyms=["삼성에어컨", "LG에어컨", "스탠드에어컨"], category_id="appliance.living.ac", search_count=580),
    _kw("청소기", synonyms=["로봇청소기", "무선청소기", "다이슨"], category_id="appliance.living.vacuum", search_count=450),
    _kw("공기청정기", synonyms=["LG퓨리케어", "삼성블루스카이"], category_id="appliance.living.air_purifier", search_count=380),
    _kw("TV", synonyms=["텔레비전", "OLED", "스마트TV", "4K TV"], category_id="appliance.video.tv", search_count=580),
    _kw("스마트폰", synonyms=["갤럭시", "아이폰", "iPhone", "Galaxy"], category_id="digital.mobile.smartphone", search_count=780),
    _kw("노트북", synonyms=["맥북", "그램", "갤럭시북", "MacBook"], category_id="digital.computer.laptop", search_count=620),
    _kw("이어폰", synonyms=["에어팟", "AirPods", "갤럭시버즈"], category_id="digital.audio.earphone", search_count=520),
    _kw("헤드폰", synonyms=["소니헤드폰", "보스헤드폰"], category_id="digital.audio.headphone", search_count=350),
    _kw("태블릿", synonyms=["아이패드", "iPad", "갤럭시탭"], category_id="digital.mobile.tablet", search_count=450),

    # ═══════════════════════════════════════
    # 화장품
    # ═══════════════════════════════════════
    _kw("선크림", synonyms=["자외선차단제", "썬크림", "SPF50"], category_id="cosmetics.skincare.sunscreen", search_count=450),
    _kw("마스크팩", synonyms=["시트마스크", "팩"], category_id="cosmetics.skincare.mask", search_count=380),
    _kw("립스틱", synonyms=["틴트", "립밤"], category_id="cosmetics.makeup.lipstick", search_count=420),
    _kw("클렌징폼", synonyms=["세안제", "폼클렌저"], category_id="cosmetics.cleansing.foam", search_count=350),

    # ═══════════════════════════════════════
    # 여행
    # ═══════════════════════════════════════
    _kw("호텔", synonyms=["호텔예약", "호캉스"], category_id="travel.domestic.hotel", search_count=520),
    _kw("항공권", synonyms=["비행기표", "특가항공"], category_id="travel.international.flight", search_count=580),
    _kw("펜션", synonyms=["풀빌라", "독채펜션"], category_id="travel.domestic.pension", search_count=380),

    # ═══════════════════════════════════════
    # 반려동물
    # ═══════════════════════════════════════
    _kw("강아지사료", synonyms=["개사료", "로얄캐닌", "뉴트로"], category_id="pet.dog.food", search_count=420),
    _kw("고양이사료", synonyms=["캣푸드", "로얄캐닌고양이"], category_id="pet.cat.food", search_count=380),
    _kw("고양이모래", synonyms=["캣리터", "모래"], category_id="pet.cat.litter", search_count=310),

    # ═══════════════════════════════════════
    # 브랜드 키워드
    # ═══════════════════════════════════════
    _kw("농심", synonyms=["nongshim"], category_id="processed.noodle.ramen", search_count=450),
    _kw("오뚜기", synonyms=["ottogi"], category_id="processed.noodle.ramen", search_count=420),
    _kw("CJ", synonyms=["CJ제일제당", "비비고"], category_id="processed", search_count=380),
    _kw("풀무원", synonyms=["pulmuone"], category_id="processed.tofu", search_count=350),
    _kw("동원", synonyms=["동원F&B", "동원참치"], category_id="processed.canned.tuna", search_count=380),
    _kw("사조", synonyms=["사조대림"], category_id="processed.canned", search_count=280),
    _kw("삼성", synonyms=["Samsung", "삼성전자"], category_id="digital", search_count=580),
    _kw("LG", synonyms=["LG전자", "엘지"], category_id="appliance", search_count=520),
    _kw("나이키", synonyms=["Nike"], category_id="clothing.shoes", search_count=480),
    _kw("아디다스", synonyms=["Adidas"], category_id="clothing.shoes", search_count=420),
    _kw("이마트", synonyms=["emart", "SSG"], category_id=None, search_count=680),
    _kw("홈플러스", synonyms=["homeplus"], category_id=None, search_count=520),
    _kw("롯데마트", synonyms=["lottemart"], category_id=None, search_count=480),
    _kw("코스트코", synonyms=["costco", "코스코"], category_id=None, search_count=620),
    _kw("쿠팡", synonyms=["coupang", "로켓배송"], category_id=None, search_count=780),
    _kw("GS25", synonyms=["지에스25"], category_id=None, search_count=380),
    _kw("CU", synonyms=["씨유", "BGF"], category_id=None, search_count=350),
    _kw("세븐일레븐", synonyms=["7-eleven", "711"], category_id=None, search_count=310),

    # ═══════════════════════════════════════
    # 일반 검색어 / 핫딜 용어
    # ═══════════════════════════════════════
    _kw("1+1", synonyms=["원플러스원", "하나사면하나"], category_id=None, search_count=1100),
    _kw("2+1", synonyms=["투플러스원"], category_id=None, search_count=650),
    _kw("반값", synonyms=["반값할인", "50%할인"], category_id=None, search_count=780),
    _kw("할인", synonyms=["세일", "sale", "discount"], category_id=None, search_count=950),
    _kw("특가", synonyms=["초특가", "파격특가"], category_id=None, search_count=850),
    _kw("핫딜", synonyms=["hotdeal", "hot deal", "떠리"], category_id=None, search_count=920),
    _kw("타임세일", synonyms=["타임딜", "시간한정"], category_id=None, search_count=480),
    _kw("무료배송", synonyms=["배송무료", "free shipping"], category_id=None, search_count=520),
    _kw("쿠폰", synonyms=["할인쿠폰", "coupon"], category_id=None, search_count=580),
    _kw("적립", synonyms=["포인트", "적립금"], category_id=None, search_count=380),
    _kw("최저가", synonyms=["최저", "최저가격"], category_id=None, search_count=720),
    _kw("가격비교", synonyms=["비교", "가격"], category_id=None, search_count=650),

    # ═══════════════════════════════════════
    # 단위/용량 키워드
    # ═══════════════════════════════════════
    _kw("계란 30구", synonyms=["달걀 30알", "계란한판"], category_id="livestock.egg", search_count=480),
    _kw("우유 1L", synonyms=["우유 1리터"], category_id="dairy.milk", search_count=380),
    _kw("생수 2L", synonyms=["물 2리터"], category_id="beverage.water.still", search_count=350),
    _kw("쌀 10kg", synonyms=["쌀 10킬로"], category_id="agriculture.grain.rice", search_count=450),
    _kw("쌀 20kg", synonyms=["쌀 20킬로"], category_id="agriculture.grain.rice", search_count=420),
    _kw("삼겹살 1kg", synonyms=["삼겹살 100g"], category_id="livestock.pork.belly", search_count=380),

    # ═══════════════════════════════════════
    # 마트별 검색
    # ═══════════════════════════════════════
    _kw("이마트 삼겹살", category_id="livestock.pork.belly", search_count=320),
    _kw("코스트코 삼겹살", category_id="livestock.pork.belly", search_count=310),
    _kw("이마트 계란", category_id="livestock.egg", search_count=280),
    _kw("쿠팡 생수", category_id="beverage.water.still", search_count=310),
    _kw("홈플러스 우유", category_id="dairy.milk", search_count=250),

    # ═══════════════════════════════════════
    # 시즌/이벤트 키워드
    # ═══════════════════════════════════════
    _kw("김장", synonyms=["김장배추", "김장재료", "김장세트"], category_id="agriculture.leafy.napa_cabbage", search_count=580),
    _kw("추석선물", synonyms=["명절선물", "추석선물세트"], category_id="etc.gift_set", search_count=480),
    _kw("설날선물", synonyms=["설선물세트"], category_id="etc.gift_set", search_count=420),
    _kw("어버이날선물", synonyms=["어버이날"], category_id="etc.gift_set", search_count=310),
    _kw("크리스마스케이크", synonyms=["크리스마스", "케이크"], category_id="processed.bakery.cake", search_count=350),
    _kw("밸런타인초콜릿", synonyms=["밸런타인", "밸런타인데이"], category_id="snack.chocolate", search_count=280),

    # ═══════════════════════════════════════
    # 가구/생활
    # ═══════════════════════════════════════
    _kw("소파", synonyms=["거실소파", "가죽소파"], category_id="furniture.living.sofa", search_count=380),
    _kw("침대", synonyms=["퀸침대", "싱글침대"], category_id="furniture.bedroom.bed", search_count=350),
    _kw("매트리스", synonyms=["메모리폼", "스프링매트리스"], category_id="furniture.bedroom.mattress", search_count=310),
    _kw("책상", synonyms=["컴퓨터책상", "학생책상"], category_id="furniture.study.desk", search_count=280),

    # ═══════════════════════════════════════
    # 기타 추가 키워드
    # ═══════════════════════════════════════
    _kw("상품권", synonyms=["백화점상품권", "문화상품권"], category_id="etc.voucher", search_count=480),
    _kw("기프트카드", synonyms=["선불카드", "gift card"], category_id="etc.gift_card", search_count=310),
    _kw("영화관", synonyms=["CGV", "메가박스", "롯데시네마"], category_id="culture.movie.cinema", search_count=450),
    _kw("OTT", synonyms=["넷플릭스", "왓챠", "디즈니플러스", "티빙"], category_id="culture.movie.ott", search_count=420),
    _kw("콘서트", synonyms=["공연", "라이브"], category_id="culture.performance.concert", search_count=380),

    _kw("KTX", synonyms=["케이티엑스", "기차표"], category_id="travel.domestic.ktx", search_count=350),
    _kw("렌터카", synonyms=["렌트카", "렌터카예약"], category_id="travel.domestic.rental_car", search_count=310),

    _kw("면도기", synonyms=["질레트", "전동면도기"], category_id="cosmetics.men_cosmetic.razor", search_count=310),

    _kw("게임기", synonyms=["PS5", "닌텐도스위치", "Xbox"], category_id="digital.gaming.console", search_count=380),

    _kw("생리대", synonyms=["오버나이트", "날개형"], category_id="household.sanitary.pad", search_count=310),
    _kw("건전지", synonyms=["AA건전지", "AAA건전지", "듀라셀"], category_id="household.battery.battery", search_count=280),

    # ═══════════════════════════════════════
    # 추가 식품 키워드 (500+ 목표 달성)
    # ═══════════════════════════════════════
    _kw("떡볶이", synonyms=["밀떡볶이", "쌀떡볶이", "떡볶이소스"], category_id="restaurant.snack_bar", search_count=620),
    _kw("김밥", synonyms=["충무김밥", "참치김밥"], category_id="restaurant.snack_bar", search_count=480),
    _kw("짜장면", synonyms=["짜장", "자장면"], category_id="delivery.chinese_food", search_count=520),
    _kw("짬뽕", synonyms=["해물짬뽕"], category_id="delivery.chinese_food", search_count=380),
    _kw("돈카츠", synonyms=["돈까스", "돈가스", "경양식"], category_id="restaurant.japanese", search_count=420),
    _kw("스테이크", synonyms=["한우스테이크", "티본"], category_id="restaurant.western", search_count=380),
    _kw("삼다수", synonyms=["제주삼다수"], category_id="beverage.water.still", search_count=420),
    _kw("제로콜라", synonyms=["코카콜라제로", "펩시제로"], category_id="beverage.soda.cola", search_count=520),
    _kw("햇반", synonyms=["CJ햇반", "즉석밥"], category_id="processed.instant.rice", search_count=480),
    _kw("비비고", synonyms=["비비고만두", "비비고국"], category_id="processed.frozen.dumpling", search_count=520),
    _kw("맥심", synonyms=["맥심모카골드", "맥심커피"], category_id="beverage.coffee.mix", search_count=380),
    _kw("카누", synonyms=["맥심카누"], category_id="beverage.coffee.instant", search_count=350),
    _kw("서울우유", synonyms=["서울유업"], category_id="dairy.milk.plain", search_count=420),
    _kw("매일우유", synonyms=["매일유업"], category_id="dairy.milk.plain", search_count=350),
    _kw("참이슬", synonyms=["참이슬오리지널", "참이슬후레쉬"], category_id="alcohol.soju", search_count=450),
    _kw("처음처럼", synonyms=["순하리"], category_id="alcohol.soju", search_count=380),
    _kw("정관장", synonyms=["정관장홍삼정"], category_id="health.ginseng", search_count=420),
    _kw("락토핏", synonyms=["종근당락토핏"], category_id="health.probiotic", search_count=350),
    _kw("다이슨", synonyms=["dyson", "다이슨청소기", "다이슨에어랩"], category_id="appliance.living.vacuum", search_count=480),
    _kw("로봇청소기", synonyms=["로보락", "에코백스"], category_id="appliance.living.vacuum", search_count=380),
    _kw("갤럭시", synonyms=["갤럭시S", "갤럭시Z"], category_id="digital.mobile.smartphone", search_count=620),
    _kw("아이폰", synonyms=["iPhone", "아이폰프로"], category_id="digital.mobile.smartphone", search_count=680),
    _kw("에어팟", synonyms=["AirPods", "에어팟프로"], category_id="digital.audio.earphone", search_count=520),
    _kw("아이패드", synonyms=["iPad", "아이패드프로"], category_id="digital.mobile.tablet", search_count=480),
    _kw("맥북", synonyms=["MacBook", "맥북프로", "맥북에어"], category_id="digital.computer.laptop", search_count=450),
    _kw("닌텐도", synonyms=["닌텐도스위치", "Nintendo"], category_id="digital.gaming.console", search_count=380),

    # 추가 농산물
    _kw("귤", synonyms=["감귤", "한라봉", "천혜향"], category_id="agriculture.fruit.tangerine", search_count=720),
    _kw("방울토마토", synonyms=["대추방울토마토"], category_id="agriculture.fruit_veg.tomato", search_count=420),

    # 추가 유통/마트 관련
    _kw("오늘의특가", synonyms=["오특", "데일리특가"], category_id=None, search_count=420),
    _kw("장보기", synonyms=["장바구니", "마트장보기"], category_id=None, search_count=380),
    _kw("배송", synonyms=["새벽배송", "당일배송", "익일배송"], category_id=None, search_count=450),

    # 추가 가전
    _kw("건조기", synonyms=["LG건조기", "삼성건조기"], category_id="appliance.living.dryer", search_count=380),
    _kw("식기세척기", synonyms=["식세기"], category_id="appliance.kitchen.dishwasher", search_count=350),
    _kw("전자레인지", synonyms=["전자렌지"], category_id="appliance.kitchen.microwave", search_count=310),

    # 추가 의류/패션
    _kw("패딩", synonyms=["롱패딩", "숏패딩", "경량패딩"], category_id="clothing.men.jacket", search_count=480),
    _kw("후드티", synonyms=["후드", "맨투맨"], category_id="clothing.men.tshirt", search_count=350),
    _kw("레깅스", synonyms=["요가레깅스", "운동레깅스"], category_id="clothing.sports.yoga", search_count=380),
]


# ──────────────────────────────────────────────
# 동의어(synonym) 역매핑
# ──────────────────────────────────────────────

SYNONYMS: dict[str, str] = {}
"""동의어 → 원래 키워드 매핑. 예: {"달걀": "계란", "삼겹": "삼겹살"}"""

_RELATED: dict[str, list[str]] = {}
"""키워드 → 관련 키워드 매핑."""


def _build_synonym_maps():
    """내부: 동의어/관련어 맵 빌드."""
    SYNONYMS.clear()
    _RELATED.clear()
    for kw in KEYWORDS:
        for syn in kw["synonyms"]:
            if syn not in SYNONYMS:
                SYNONYMS[syn] = kw["word"]
        _RELATED[kw["word"]] = list(kw["synonyms"])


_build_synonym_maps()


# ──────────────────────────────────────────────
# 사전 인덱스 — O(1) 조회용 (auto_categorize 핫패스 최적화)
# ──────────────────────────────────────────────

# word → keyword dict (정확 일치 조회)
KEYWORD_BY_WORD: dict[str, dict] = {kw["word"]: kw for kw in KEYWORDS}

# synonym → keyword dict (동의어 역매핑으로 O(1) 조회)
KEYWORD_BY_SYNONYM: dict[str, dict] = {}
for _kw_entry in KEYWORDS:
    for _syn in _kw_entry.get("synonyms", []):
        if _syn not in KEYWORD_BY_SYNONYM:
            KEYWORD_BY_SYNONYM[_syn] = _kw_entry

# category_id → [keyword dicts] 인덱스
KEYWORDS_BY_CATEGORY: dict[str, list[dict]] = {}
for _kw_entry in KEYWORDS:
    _cid = _kw_entry.get("category_id")
    if _cid:
        KEYWORDS_BY_CATEGORY.setdefault(_cid, []).append(_kw_entry)


def resolve_synonym(query: str) -> str:
    """동의어를 원래 키워드로 변환. 없으면 원래 쿼리 반환."""
    return SYNONYMS.get(query, query)


def get_related(word: str) -> list[str]:
    """키워드의 관련어(동의어 + 유사어) 반환."""
    return _RELATED.get(word, [])


def get_keywords_for_category(category_id: str) -> list[dict]:
    """특정 카테고리에 속한 키워드 목록. 사전 인덱스로 O(1) 조회."""
    return list(KEYWORDS_BY_CATEGORY.get(category_id, []))


def search_keywords(query: str, limit: int = 10) -> list[dict]:
    """
    키워드 검색 (접두사 매칭 + 동의어 검색).

    1. 정확히 일치하는 키워드
    2. 접두사로 시작하는 키워드 (인기순)
    3. 동의어가 매칭되는 키워드
    """
    query_lower = query.lower()
    exact = []
    prefix = []
    synonym_matches = []

    for kw in KEYWORDS:
        if not kw["is_active"]:
            continue
        word_lower = kw["word"].lower()
        if word_lower == query_lower:
            exact.append(kw)
        elif word_lower.startswith(query_lower):
            prefix.append(kw)
        else:
            for syn in kw["synonyms"]:
                if syn.lower().startswith(query_lower):
                    synonym_matches.append(kw)
                    break

    prefix.sort(key=lambda x: x["search_count"], reverse=True)
    synonym_matches.sort(key=lambda x: x["search_count"], reverse=True)

    results = exact + prefix + synonym_matches
    return results[:limit]


def get_popular_keywords(limit: int = 20) -> list[dict]:
    """인기 키워드 반환 (search_count 순)."""
    active = [kw for kw in KEYWORDS if kw["is_active"]]
    active.sort(key=lambda x: x["search_count"], reverse=True)
    return active[:limit]


# ──────────────────────────────────────────────
# 인기 검색 패턴
# ──────────────────────────────────────────────

POPULAR_PATTERNS: list[dict] = [
    # [마트명] [상품] 패턴
    {"pattern": "{store} {product}", "examples": ["이마트 삼겹살", "코스트코 계란", "홈플러스 우유"],
     "stores": ["이마트", "홈플러스", "롯데마트", "코스트코", "쿠팡", "GS25", "CU"]},

    # [상품] [단위] 패턴
    {"pattern": "{product} {unit}", "examples": ["계란 30구", "쌀 10kg", "우유 1L", "생수 2L"],
     "units": ["개", "팩", "봉지", "상자", "kg", "g", "L", "mL", "구", "입"]},

    # [카테고리] 핫딜 패턴
    {"pattern": "{category} 핫딜", "examples": ["과일 핫딜", "축산물 핫딜", "가전 핫딜"],
     "keywords": ["핫딜", "특가", "세일", "할인"]},

    # [브랜드] [제품] 패턴
    {"pattern": "{brand} {product}", "examples": ["농심 라면", "CJ 햇반", "삼성 갤럭시"],
     "brands": ["농심", "오뚜기", "CJ", "풀무원", "삼성", "LG", "나이키"]},

    # [할인유형] 패턴
    {"pattern": "{deal_type}", "examples": ["1+1", "반값", "타임세일"],
     "deal_types": ["1+1", "2+1", "반값", "특가", "타임세일", "무료배송"]},
]
