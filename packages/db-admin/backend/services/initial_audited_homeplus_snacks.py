"""Reviewed snack/bakery forms inside mixed Homeplus merchandising shelves.

Exact title/path evidence only. Unknown frozen-drink brands and DIY kits are
not assumed to be ready-made cookies or pudding. Flavor words inside a cereal
or bread name do not change the product into chocolate/cookies/cream cheese.
"""
ROOT='과자/시리얼'
CREAM=(ROOT,'과자/쿠키/파이','샌드/웨하스','크림비스켓')
BUTTER=(ROOT,'과자/쿠키/파이','비스켓/쿠키/프레첼','버터비스켓')
GRAIN=(ROOT,'과자/쿠키/파이','쌀/곡물 과자','기타곡물스낵')
CHOCO=(ROOT,'시리얼/간식류소시지','어린이용 시리얼','초코')
JELLY=(ROOT,'초콜릿/캔디/젤리/껌','젤리/푸딩','젤리/푸딩')
FROZEN=('냉장/냉동/밀키트','아이스크림/디저트/얼음','디저트','냉동케익/푸딩/마카롱')
GROUPS={
 'food.snacks.baked.wafer': ((CREAM,('크라운 초코하임 142G','크라운 화이트하임 142G','크라운 화이트하임 284G','크라운 초코하임 284G','해태 크림 미니웨하스 150G','로아커 웨하스 바닐라 125G')),),
 'food.snacks.baked.biscuits': ((CREAM,('크라운 쿠크다스 커피 289G','크라운 쿠크다스 화이트 289G')),),
 'food.snacks.baked.cracker': ((BUTTER,('플레인 크래커 340G','해태 아이비 크래커 155G','참깨 크래커 340G','오리지널 크래커 500G','퀴노아크래커 340G','롯데 야채크래커 249G')),),
 'food.snacks.baked.sandwich': ((BUTTER,('해태 샌드에이스 크림라떼 204G',)),),
 'food.snacks.baked.pie': ((BUTTER,('롯데 엄마손파이 254G',)),),
 'food.snacks.cereal.chocolate': ((CHOCO,('동서 오곡 코코볼 570G','동서 오곡 코코볼 컵 30G','농심 켈로그 오곡 첵스 초코 570G','켈로그 첵스초코 쿠키앤크림 420G','농심 켈로그 첵스초코 컵 30G')),),
 'food.snacks.bars.protein': ((GRAIN,('켈로그 단백질바K 헤이즐넛&다크초코 120G',)),),
 'food.snacks.traditional.hangwa': ((GRAIN,('오리온 땅콩강정 65G','오리온 땅콩강정 3번들 80G*3')),),
 'food.bakery.dessert.churros': ((FROZEN,('씨제이 고메 츄러스 시나몬 262G',)),),
 'food.bakery.bread.filled': ((FROZEN,('화정당 모짜렐라 십원빵 360G','화정당 슈크림 십원빵 360G')),),
 'food.bakery.bread.bagel': ((FROZEN,('풀무원 바질토마토크림치즈베이글 435G','풀무원 대파크림치즈베이글 405G')),),
 'food.bakery.bread.hard': ((FROZEN,('널담 네모바게트 치즈올리브 450G','널담 네모바게트 플레인 450G')),),
}
ENTRIES={(path,title):leaf for leaf,groups in GROUPS.items() for path,titles in groups for title in titles}


def reviewed_homeplus_snack_leaf(evidence):
    if evidence['mart']!='homeplus':
        return None
    return ENTRIES.get((tuple(evidence['source_path_parts']),evidence['source_title']))
