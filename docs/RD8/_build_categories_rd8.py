# -*- coding: utf-8 -*-
"""RD8 C3 카테고리 트리 빌더.

C1(opus) 초안 + C2(gpt5.5) 적대적 검토 의사결정을 반영한 최종 트리를 생성.
실행 결과:
  - packages/shared/data/categories_rd8.yaml
  - 검증 로그 stdout
  - 실 raw 800건 distinct 상품명 매핑 시뮬레이션
"""
from __future__ import annotations
import json, os, re, sys, glob, io
from collections import OrderedDict, Counter

# ─────────────────────────────────────────────────────────────────────
# 노드 정의 (id, parent, display_name_ko, unit_kind_default, keyword_seeds, notes)
# unit_kind_default 값: weight | volume | count | pack
# parent=None 이면 도메인 루트.
# id 정책: snake_case 영문 + "." 네임스페이스 (각 segment snake_case). C1과 호환.
# ─────────────────────────────────────────────────────────────────────

N = []  # list of dict

def add(id_, name, parent=None, unit='count', seeds=None, notes=None):
    N.append({
        'id': id_, 'display_name_ko': name, 'parent': parent,
        'unit_kind_default': unit,
        'keyword_seeds': seeds or [],
        'notes': notes or '',
    })

# ══════════════════════════════════════════════════════════════
# DOMAIN: food
# ══════════════════════════════════════════════════════════════
add('food', '식료품', None, 'weight', notes='마트 4사 매출의 대부분. 신선/냉장가공/냉동/상온가공/음료를 하위로.')

# ─── 신선 ───
add('food.fresh', '신선식품', 'food', 'weight')

# 채소
add('food.fresh.vegetable', '채소', 'food.fresh', 'weight')
add('food.fresh.vegetable.leaf', '잎채소·쌈채소', 'food.fresh.vegetable', 'weight',
    ['배추', '양배추', '상추', '시금치', '깻잎', '청경채', '케일', '쌈채소', '부추', '알배기배추', '봄동', '적채', '엽채류'],
    'C2§4 채택: "엽채류"→"잎채소·쌈채소" 일반어. alias 엽채류 keyword 보존.')
add('food.fresh.vegetable.potato_sweet_potato', '감자·고구마', 'food.fresh.vegetable', 'weight',
    ['감자', '수미감자', '햇감자', '고구마', '호박고구마', '꿀고구마', '밤고구마', '자색고구마'],
    'C2§2 채택: root 4분할. 감자류 독립.')
add('food.fresh.vegetable.onion_garlic', '양파·마늘·생강', 'food.fresh.vegetable', 'weight',
    ['양파', '햇양파', '적양파', '마늘', '깐마늘', '다진마늘', '통마늘', '생강', '쪽파'],
    'C2§2 채택: 양념류 뿌리채소 묶음. raw 매핑 잦음.')
add('food.fresh.vegetable.radish_carrot', '무·당근·뿌리채소', 'food.fresh.vegetable', 'weight',
    ['무', '알타리무', '김장무', '당근', '미니당근', '우엉', '연근', '비트', '도라지', '더덕', '근채류'],
    'C2§2 채택: 일반 뿌리채소.')
add('food.fresh.vegetable.fruit_vegetable', '오이·호박·고추·토마토', 'food.fresh.vegetable', 'weight',
    ['파프리카', '피망', '고추', '오이', '호박', '애호박', '가지', '토마토', '방울토마토', '대추방울토마토', '단호박', '풋고추', '청양고추', '과채류'],
    'C2§4·§5 채택: display 일반어, unit weight(홈플 방울토마토 500/900g). raw "애호박 1개" 흡수.')
add('food.fresh.vegetable.mushroom', '버섯', 'food.fresh.vegetable', 'weight',
    ['느타리', '새송이', '표고', '팽이', '만가닥', '양송이', '목이', '송이', '능이', '버섯'])
add('food.fresh.vegetable.herb_green_onion', '대파·쪽파·허브', 'food.fresh.vegetable', 'weight',
    ['대파', '쪽파', '실파', '미나리', '바질', '로즈마리', '파슬리', '고수', '민트', '향신채'],
    'C2§4 채택: "허브·향신채"→일상어. 마늘은 onion_garlic으로 이동.')
add('food.fresh.vegetable.sprout_bean', '콩나물·새싹', 'food.fresh.vegetable', 'weight',
    ['콩나물', '숙주', '새싹채소', '알팔파', '무순'])
add('food.fresh.vegetable.pickled', '절임배추·김장재료', 'food.fresh.vegetable', 'weight',
    ['절임배추', '김장배추', '갓', '알타리', '쪽파묶음', '김장무'])

# 과일
add('food.fresh.fruit', '과일', 'food.fresh', 'count')
add('food.fresh.fruit.citrus', '감귤류', 'food.fresh.fruit', 'weight',
    ['귤', '오렌지', '레몬', '자몽', '라임', '한라봉', '천혜향', '만감류', '레드향', '카라카라'])
add('food.fresh.fruit.berry', '딸기·블루베리', 'food.fresh.fruit', 'weight',
    ['딸기', '설향딸기', '블루베리', '라즈베리', '크랜베리', '산딸기', '베리류'],
    'C2§5 채택: count→weight (g/팩 단가가 일반적).')
add('food.fresh.fruit.tropical', '바나나·키위·아보카도·열대과일', 'food.fresh.fruit', 'count',
    ['바나나', '키위', '골드키위', '제스프리', '썬골드키위', '그린키위', '파인애플', '망고', '아보카도', '석류', '용과', '패션후르츠', '코코넛'],
    'C2§1+§5 채택: 키위/석류/아보카도 alias 흡수. raw "제스프리 골드키위 EA" 흡수. count default + mixed(count, weight).')
add('food.fresh.fruit.melon', '멜론·수박·참외', 'food.fresh.fruit', 'count',
    ['수박', '멜론', '참외', '머스크멜론', '애플수박', '백종원수박'])
add('food.fresh.fruit.apple_pear', '사과·배', 'food.fresh.fruit', 'count',
    ['사과', '부사', '홍로', '아오리', '배', '신고배', '햇사과', '햇배'],
    'C2§2 채택: stone_pome 분할.')
add('food.fresh.fruit.peach_plum_cherry', '복숭아·자두·체리', 'food.fresh.fruit', 'count',
    ['복숭아', '자두', '천도복숭아', '체리', '황도', '백도', '대추'],
    'C2§2 채택: stone_pome 분할.')
add('food.fresh.fruit.grape', '포도류', 'food.fresh.fruit', 'weight',
    ['포도', '청포도', '샤인머스캣', '거봉', '캠벨'])

# 정육
add('food.fresh.meat', '정육', 'food.fresh', 'weight')
add('food.fresh.meat.beef_domestic', '국내산 소고기', 'food.fresh.meat', 'weight',
    ['한우', '국내산소고기', '등심', '안심', '채끝', '갈비', '양지', '사태', '차돌박이', '국거리', '다짐육'])
add('food.fresh.meat.beef_imported', '수입 소고기', 'food.fresh.meat', 'weight',
    ['미국산소고기', '호주산소고기', '청정우', '척아이롤', '부채살', '토마호크', '살치살', 'LA갈비', '불고기', '샤브샤브'],
    '홈플 fixture: 호주청정우 앞다리 불고기&샤브샤브.')
add('food.fresh.meat.pork_belly_neck', '돼지 삼겹살·목살', 'food.fresh.meat', 'weight',
    ['삼겹살', '오겹살', '목살', '항정살', '가브리살', '갈매기살', '구이용돼지'],
    'C2§2 채택: pork 분할. raw "국내산 돼지 삼겹살 600g" 흡수.')
add('food.fresh.meat.pork_leg_shoulder', '돼지 앞다리·뒷다리·다짐육', 'food.fresh.meat', 'weight',
    ['앞다리', '뒷다리', '돼지다짐육', '제육볶음용', '돈가스용', '국내산돼지'])
add('food.fresh.meat.pork_rib', '돼지 갈비·등갈비', 'food.fresh.meat', 'weight',
    ['돼지갈비', '등갈비', 'LA식돼지갈비', '양념돼지갈비'])
add('food.fresh.meat.chicken_whole_parts', '생닭·닭다리·날개', 'food.fresh.meat', 'weight',
    ['생닭', '통닭', '백숙용닭', '닭다리', '닭날개', '닭정육', '닭안심', '영계', '토종닭'],
    'C2§2 채택: chicken 분할.')
add('food.fresh.meat.chicken_breast', '닭가슴살', 'food.fresh.meat', 'weight',
    ['닭가슴살', '안심살', '닭가슴살큐브', '닭가슴살스테이크', '냉장닭가슴살'])
add('food.fresh.meat.chicken_processed', '훈제닭·조리된 닭', 'food.fresh.meat', 'weight',
    ['훈제닭', '훈제닭가슴살', '슬라이스닭가슴살', '닭가슴살소시지', '데리야끼닭', '바베큐치킨'],
    'C2§1·§6 채택: 코스트코 Smoked-Chicken-Breast 흡수.')
add('food.fresh.meat.duck_lamb', '오리·양고기', 'food.fresh.meat', 'weight',
    ['오리', '훈제오리', '양고기', '양갈비', '램찹', '칠면조'])

# 계란
add('food.fresh.egg', '계란·알류', 'food.fresh', 'count',
    ['계란', '특란', '대란', '왕란', '무항생제', '동물복지', '유정란', '메추리알', '30구', '15구', '10구', '행복생생란'],
    'raw fixture: 행복생생란 특란 30입 1.8KG. count 단가(30구) 비교.')

# 수산
add('food.fresh.seafood', '수산물', 'food.fresh', 'weight')
add('food.fresh.seafood.fish_white_blue', '고등어·갈치·삼치 등 일반 생선', 'food.fresh.seafood', 'weight',
    ['고등어', '갈치', '삼치', '조기', '임연수', '명태', '가자미', '광어', '우럭', '도미', '병어'],
    'C2§2 채택: fish_fresh 분할 (일반 선어).')
add('food.fresh.seafood.salmon_tuna', '연어·참치·회감', 'food.fresh.seafood', 'weight',
    ['연어', '훈제연어', '참치회', '참치뱃살', '광어회', '연어회'])
add('food.fresh.seafood.fish_dried_salted', '굴비·자반·황태', 'food.fresh.seafood', 'weight',
    ['굴비', '참굴비', '영광굴비', '자반고등어', '황태', '북어', '쥐포', '오징어채', '진미채', '노가리'],
    '홈플 fixture: 영광 참굴비 1.0kg/20마리. 양반 오징어채볶음 raw 매핑.')
add('food.fresh.seafood.anchovy_dried', '멸치·건어물', 'food.fresh.seafood', 'weight',
    ['멸치', '잔멸치', '다시멸치', '국물멸치', '볶음멸치', '디포리', '새우건조'])
add('food.fresh.seafood.shellfish', '조개·패류', 'food.fresh.seafood', 'weight',
    ['바지락', '홍합', '가리비', '굴', '전복', '모시조개', '백합', '키조개'])
add('food.fresh.seafood.cephalopod', '오징어·문어·낙지', 'food.fresh.seafood', 'weight',
    ['오징어', '문어', '낙지', '주꾸미', '한치', '갑오징어'])
add('food.fresh.seafood.crustacean', '새우·게·갑각류', 'food.fresh.seafood', 'weight',
    ['새우', '대하', '흰다리새우', '꽃게', '대게', '킹크랩', '랍스터', '가재'])
add('food.fresh.seafood.seaweed_dried', '미역·다시마·해조류', 'food.fresh.seafood', 'weight',
    ['미역', '다시마', '톳', '매생이', '파래', '미역줄기', '건미역'],
    'C2§2 채택: seaweed 분할.')
add('food.fresh.seafood.seaweed_laver', '김·조미김·김자반', 'food.fresh.seafood', 'count',
    ['김', '재래김', '돌김', '곱창김', '조미김', '도시락김', '김자반', '광천김', '대천김'],
    'C2§1·§2 채택: 김 독립 leaf. 도시락김 매수 비교가 일반적이라 count.')
add('food.fresh.seafood.frozen', '냉동 수산물', 'food.fresh.seafood', 'weight',
    ['냉동새우', '냉동연어', '냉동대게', '냉동주꾸미', '냉동조개', '냉동굴'])

# ─── 냉장가공 (신설 — C2§6 P0) ───
add('food.chilled', '냉장 가공·반찬', 'food', 'weight',
    notes='C2 P0 채택: 신설 도메인. 두부·김치·반찬·어묵·냉장 가공육은 신선 원물이 아니라 냉장 가공.')
add('food.chilled.tofu', '두부·순두부·유부', 'food.chilled', 'weight',
    ['두부', '부침두부', '찌개두부', '순두부', '연두부', '유부', '풀무원', '국산두부', '나또'],
    'C2§6 채택: parent food.fresh→food.chilled. 롯데 fixture: 풀무원 국산 부침두부 340G.')
add('food.chilled.banchan_kimchi', '김치·반찬·젓갈', 'food.chilled', 'weight',
    ['김치', '포기김치', '깍두기', '총각김치', '열무김치', '백김치', '묵은지', '젓갈', '장아찌', '나물반찬'],
    'C2§6 채택: parent food.fresh→food.chilled.')
add('food.chilled.fishcake_crabstick_pickled', '어묵·맛살·단무지', 'food.chilled', 'weight',
    ['어묵', '어묵꼬치', '사각어묵', '환공어묵', '맛살', '게맛살', '단무지', '쌈무'],
    'C2§1 P0 채택: 홈플 "어묵/맛살/단무지" 경로 흡수. 환공어묵 부산명품 어묵꼬치 350G.')
add('food.chilled.processed_meat', '햄·소시지·베이컨', 'food.chilled', 'weight',
    ['햄', '소시지', '베이컨', '비엔나', '살라미', '프랑크', '슬라이스햄', '훈제햄', '너겟'],
    'C2§6 채택: food.fresh.meat.processed→food.chilled.processed_meat. 정육 부위 비교와 분리.')

# ─── 유제품 ───
add('food.dairy', '유제품', 'food', 'volume')
add('food.dairy.milk', '우유', 'food.dairy', 'volume')
add('food.dairy.milk.white', '흰 우유', 'food.dairy.milk', 'volume',
    ['서울우유', '매일우유', '남양우유', '1A우유', '저지방우유', '무지방우유', '멸균우유', '1L', '900ml', '200ml'],
    'raw fixture: 서울우유 1A 1L.')
add('food.dairy.milk.flavored', '가공 우유 (초코·딸기·바나나)', 'food.dairy.milk', 'volume',
    ['초코우유', '딸기우유', '바나나우유', '빙그레바나나', '커피우유', '메로나우유'])
add('food.dairy.milk.plant_based', '두유·식물성 음료', 'food.dairy.milk', 'volume',
    ['두유', '베지밀', '맛있는두유GT', '아몬드브리즈', '귀리우유', '오트밀크', '코코넛밀크', '소이밀크'],
    'C2§6 검토: parent 후보 beverage.plant_based 있으나 한국 마트 매대 멘탈 모델상 우유 매대와 같이 진열 → milk 하위 유지. raw "맛있는두유GT 200ml" 흡수.')
add('food.dairy.yogurt', '요거트·발효유', 'food.dairy', 'volume')
add('food.dairy.yogurt.drinking', '마시는 요거트', 'food.dairy.yogurt', 'volume',
    ['요플레', '액티비아', '야쿠르트', '헬리코박터', '윌', '큐원', '후레쉬'])
add('food.dairy.yogurt.spoon', '떠먹는 요거트', 'food.dairy.yogurt', 'weight',
    ['요플레', '그릭요거트', '덴마크', '액티비아', '후르츠요거트', '대용량요거트'],
    'C2§5 채택: count→weight (80g x n / 400g / 900g 대용량 g 단가 비교).')
add('food.dairy.cheese_slice', '슬라이스·스트링 치즈', 'food.dairy', 'count',
    ['슬라이스치즈', '체다슬라이스', '스트링치즈', '체다', '어린이치즈'],
    'C2§2 채택: cheese 분할.')
add('food.dairy.cheese_natural', '자연치즈·모짜렐라·크림치즈', 'food.dairy', 'weight',
    ['모짜렐라', '슈레드치즈', '크림치즈', '까망베르', '파마산', '부라타', '리코타', '체다블럭', '고다', '에담'])
add('food.dairy.butter_ghee', '버터·마가린·기버터', 'food.dairy', 'weight',
    ['버터', '가염버터', '무염버터', '마가린', '기버터'],
    'C2§5 채택: butter_cream에서 분리. weight 단위.')
add('food.dairy.cream', '생크림·휘핑크림', 'food.dairy', 'volume',
    ['생크림', '휘핑크림', '사워크림', '동물성생크림', '식물성생크림'],
    'C2§5 채택: cream은 ml.')
add('food.dairy.coffee_milk', '컵커피·유음료', 'food.dairy', 'volume',
    ['바리스타룰스', '스타벅스컵커피', '컴포즈컵', '라떼', '카페라떼', '250ml컵커피'],
    'raw fixture: 매일 바리스타룰스 라떼 250ml. C2§6: 사용자가 "커피"로도 찾으므로 검색 매핑 단계에서 beverage.coffee.rtd alias 처리.')

# ─── 곡류 ───
add('food.grain', '쌀·잡곡·가루', 'food', 'weight')
add('food.grain.rice', '쌀', 'food.grain', 'weight',
    ['백미', '현미', '찹쌀', '햅쌀', '10kg쌀', '20kg쌀', '신동진', '추청', '오대미', '흑미'])
add('food.grain.mixed_grain', '잡곡·콩', 'food.grain', 'weight',
    ['보리', '귀리', '콩', '검정콩', '서리태', '팥', '수수', '기장', '율무', '렌틸콩', '병아리콩', '퀴노아'])
add('food.grain.flour_powder', '밀가루·전분·가루', 'food.grain', 'weight',
    ['밀가루', '박력분', '강력분', '부침가루', '튀김가루', '전분', '옥수수가루', '미숫가루', '빵가루'])

# ─── 면류 (C2 P0: 형태 기반 재설계) ───
add('food.noodle', '면류', 'food', 'pack')
add('food.noodle.ramen_bag', '봉지라면', 'food.noodle', 'pack',
    ['신라면', '진라면', '안성탕면', '너구리', '삼양라면', '짜파게티', '불닭볶음면', '열라면', '틈새라면', '사리곰탕', '멸치칼국수', '120g라면', '5개입라면'],
    'C2§3·§8 채택: 맛(spicy/mild) 기준→형태(봉지) 기준 재설계. raw "농심 신라면 120g", "오뚜기 진라면 매운맛 120g" 흡수.')
add('food.noodle.ramen_cup', '컵라면·사발면', 'food.noodle', 'count',
    ['컵라면', '사발면', '왕뚜껑', '컵누들', '도시락', '육개장사발면', '김치사발면', '새우탕컵', '큰컵', '미니컵'],
    'C2§3 채택: 컵 단위 비교는 count 기본 + notes mixed (65g/86g/큰컵 중량 차이는 metadata).')
add('food.noodle.ramen_bibim_jjajang', '비빔·짜장·볶음라면', 'food.noodle', 'pack',
    ['비빔면', '팔도비빔면', '골뱅이비빔면', '짜파게티', '짜왕', '진짜장', '볶음면', '쟁반짜장'],
    'C2§4 채택: "volcano" 어휘 제거.')
add('food.noodle.pasta', '파스타·스파게티', 'food.noodle', 'weight',
    ['스파게티', '페투치네', '펜네', '마카로니', '라자냐', '카펠리니', '파스타면'])
add('food.noodle.asian_noodle', '우동·소바·국수·소면', 'food.noodle', 'weight',
    ['우동', '소바', '소면', '중면', '칼국수면', '쌀국수', '메밀국수', '잔치국수', '대용량소면', '풍국면'],
    'C2§1 검토: 대용량 건면(코스트코 3.75kg)은 별 leaf 신설 대신 keyword·notes로 흡수.')
add('food.noodle.cold_chilled', '냉장 생면·냉면·쫄면·막국수', 'food.noodle', 'pack',
    ['생칼국수', '생우동', '냉면', '평양물냉면', '비빔냉면', '쫄면', '비빔쫄면', '막국수', '비빔막국수', '라이스누들', '동치미육수'],
    'C2§1·§4 채택: display에 냉면/쫄면/막국수 명시. 홈플 면사랑 동치미육수 평양물냉면 흡수.')

# ─── 과자 ───
add('food.snack', '과자·스낵', 'food', 'weight')
add('food.snack.chip', '감자·옥수수 칩', 'food.snack', 'weight',
    ['포카칩', '수미칩', '프링글스', '도리토스', '꼬깔콘', '콘칩', '오감자', '감자칩', '양파링'])
add('food.snack.biscuit_cookie', '비스킷·쿠키', 'food.snack', 'weight',
    ['오레오', '다이제', '쿠크다스', '에이스', '빠다코코낫', '칙촉', '마가렛트', '홈런볼', '카스타드'],
    'raw fixture: 크라운 쿠크다스 75g.')
add('food.snack.pie_cake', '파이·케이크류', 'food.snack', 'weight',
    ['초코파이', '몽쉘', '오예스', '빅파이', '크림파이', '허쉬크림파이', '롯데초코파이'],
    'raw fixture: 1+1 롯데 초코파이 12개입.')
add('food.snack.chocolate', '초콜릿', 'food.snack', 'weight',
    ['가나', '페레로로쉐', '킷캣', '허쉬', '토블론', '빈츠', '빼빼로', '크런키', '다크초콜릿', '자유시간'],
    'C2§4 채택: 자유시간(초코바)은 rice_cracker_popcorn에서 이쪽으로 이동.')
add('food.snack.candy_jelly_gum', '캔디·젤리·껌', 'food.snack', 'weight',
    ['하리보', '마이쮸', '츄파춥스', '사탕', '젤리', '자일리톨', '후라보노', '캔디', '츄잉껌'])
add('food.snack.korean_traditional', '한과·전통과자', 'food.snack', 'weight',
    ['맛동산', '약과', '강정', '유과', '한과', '미쯔', '인디안밥', '양갱'],
    'raw fixture: 해태 맛동산 90g.')
add('food.snack.peanut_bean_snack', '땅콩·콩과자', 'food.snack', 'weight',
    ['오징어땅콩', '콩볶음', '미니쉘', '알새우칩', '누룽지스낵', '콩순이'],
    'C2§4 채택: "legume" id 제거. raw "농심 오징어 땅콩 85g" 흡수.')
add('food.snack.rice_cracker_popcorn', '쌀과자·팝콘', 'food.snack', 'weight',
    ['쌀과자', '뻥튀기', '팝콘', '카라멜팝콘', '치즈팝콘', '누룽지칩'],
    'C2§4 채택: 자유시간 제거.')

# ─── 견과·건과 ───
add('food.dried', '견과·건과·건나물', 'food', 'weight',
    notes='C2§4 채택: display에서 "건어물" 제거 (건어물은 food.fresh.seafood.*).')
add('food.dried.nut_mix', '견과류·믹스넛', 'food.dried', 'weight',
    ['아몬드', '호두', '캐슈넛', '마카다미아', '피스타치오', '믹스넛', '하루견과', '땅콩', '잣', '헤이즐넛', '머거본'],
    '홈플: 머거본 믹스파티 프렌즈 800G.')
add('food.dried.dried_fruit', '건과일', 'food.dried', 'weight',
    ['건포도', '건망고', '건자두', '크랜베리', '대추', '곶감', '무화과', '바나나칩', '살구', '키위말랭이'])
add('food.dried.dried_vegetable', '건나물·말린채소', 'food.dried', 'weight',
    ['무말랭이', '시래기', '고사리', '취나물', '호박오가리', '표고버섯말림'])

# ─── 시리얼·베이커리 ───
add('food.breakfast', '시리얼·베이커리', 'food', 'weight')
add('food.breakfast.cereal', '시리얼·그래놀라', 'food.breakfast', 'weight',
    ['콘푸로스트', '첵스', '콘푸레이크', '그래놀라', '오트밀', '켈로그', '포스트', '뮤즐리', '시리얼바'])
add('food.breakfast.bread', '식빵·빵', 'food.breakfast', 'weight',
    ['식빵', '모닝빵', '베이글', '크루아상', '단팥빵', '소보로', '호밀빵', '통밀빵', '바게트', '깜빠뉴'])
add('food.breakfast.jam_spread', '잼·스프레드·시럽·꿀', 'food.breakfast', 'weight',
    ['딸기잼', '사과잼', '누텔라', '땅콩버터', '꿀', '메이플시럽', '아가베', '마말레이드'])
add('food.breakfast.pancake_mix', '핫케이크·믹스', 'food.breakfast', 'weight',
    ['핫케이크믹스', '팬케이크믹스', '와플믹스', '베이킹믹스'])

# ─── 간편식 (C2 P0/P1 반영) ───
add('food.meal', '간편식·즉석식', 'food', 'pack')
add('food.meal.instant_rice', '즉석밥', 'food.meal', 'count',
    ['햇반', '오뚜기밥', '즉석밥', '현미밥', '잡곡밥', '210g밥', '130g밥', '300g밥'],
    'raw fixture: CJ 햇반 210g. C2§5 notes: mixed(count, weight).')
add('food.meal.porridge', '죽·즉석죽', 'food.meal', 'count',
    ['죽', '본죽', '전복죽', '호박죽', '양반죽', '비비고죽', '단호박죽'],
    'C2§2 채택: instant_rice에서 분리.')
add('food.meal.ready_soup', '즉석국·미역국·곰탕', 'food.meal', 'pack',
    ['육개장', '미역국', '된장국', '설렁탕', '사골곰탕', '갈비탕', '비비고사골곰탕진'],
    'C2§2 채택: 국/탕 분리.')
add('food.meal.ready_stew_tang', '찌개·전골·탕', 'food.meal', 'pack',
    ['김치찌개', '부대찌개', '부대전golf', '부대전골', '닭볶음탕', '추어탕', '시래기된장국', '양반그릴리부대전골', '비비고찌개'],
    'C2§1·§2 채택: 코코달인 fixture (양반 부대전골, 통다리닭볶음탕, 남도추어탕) 흡수.')
add('food.meal.tteokbokki_rabokki', '떡볶이·라볶이', 'food.meal', 'pack',
    ['떡볶이', '비비고떡볶이', '라볶이', '짜장라볶이', '치즈떡볶이', '즉석떡볶이'],
    'C2§1 P0 채택: 비비고 떡볶이 1440G, 떡볶이의 신 짜장 라볶이 482G x 3.')
add('food.meal.cup_bowl_rice', '컵밥·덮밥', 'food.meal', 'count',
    ['컵밥', '햇반컵반', '덮밥', '치킨마요덮밥', '제육덮밥', '카레덮밥', '컵반'],
    'C2§1 P0 채택: 햇반컵반 치킨마요덮밥 233G x 6.')
add('food.meal.meal_kit', '밀키트', 'food.meal', 'weight',
    ['밀키트', '고메', '마이셰프', '프레시지', '짬뽕밀키트', '중화짬뽕', '부대찌개키트', '알리오올리오'],
    '롯데 fixture: CJ 고메 중화짬뽕 2인분 652G. C2§5 채택: count→weight.')
add('food.meal.frozen_dumpling', '냉동 만두·튀김', 'food.frozen', 'weight',
    ['비비고만두', '고향만두', '군만두', '물만두', '김치만두', '갈비만두', '새우만두'],
    'C2§6 P1 채택: parent food.meal→food.frozen.')
add('food.meal.soup_powder', '분말스프·즉석스프', 'food.meal', 'pack',
    ['양송이스프', '크림스프', '보노', '바질크림스프', 'KRAFT스프', '분말스프'],
    'C2§1 채택: 코코달인 KRAFT 양송이스프, 보노 바질크림 스프.')

# ─── 냉동 (C2 P1 신설) ───
add('food.frozen', '냉동식품', 'food', 'weight',
    notes='C2 P1 채택: 신설 도메인. 냉동 만두/피자/치킨/아이스크림/한식 정리.')
add('food.frozen.pizza_pasta', '냉동 피자·파스타', 'food.frozen', 'weight',
    ['냉동피자', 'CJ고메피자', '미스터피자', '냉동파스타', '그라탕', '라자냐'],
    'C2§5 채택: count→weight.')
add('food.frozen.chicken_hotdog', '냉동 치킨·핫도그·너겟·꼬치', 'food.frozen', 'weight',
    ['너겟', '닭강정', '치킨너겟', '핫도그', '미니핫도그', '닭꼬치', '숯불닭꼬치', '후라이드', '양념치킨', '윙'],
    'C2§1 P0 채택: 홈플 plugin "피자/핫도그/치킨" 경로의 핫도그 명시. simplus 숯불닭꼬치 520G.')
add('food.frozen.korean_tteok_jeon', '냉동 떡·전·동그랑땡', 'food.frozen', 'weight',
    ['떡갈비', '동그랑땡', '산적', '떡볶이떡', '가래떡', '모듬전', '굴비전'],
    'C2§2 채택: frozen_korean 분할.')
add('food.frozen.korean_snack', '냉동 호떡·군고구마·간식', 'food.frozen', 'weight',
    ['호떡', '군고구마', '냉동간식', '냉동붕어빵'])
add('food.frozen.western', '냉동 양식·간식 (감자·새우 등)', 'food.frozen', 'weight',
    ['감자튀김', '해쉬브라운', '모짜렐라스틱', '후라이드새우', '새우튀김', '치즈볼'])
add('food.frozen.icecream', '아이스크림·빙과', 'food.frozen', 'count',
    ['메로나', '빠삐코', '월드콘', '부라보콘', '투게더', '하겐다즈', '베스킨라빈스', '비비빅', '죠스바', '끌레도르', '파인트아이스크림'],
    'C2§6 채택: food.meal→food.frozen.icecream. id에서 "frozen_ice" 모호함 제거.')

# ─── 양념·소스·오일 ───
add('food.condiment', '장류·양념·소스', 'food', 'volume')
add('food.condiment.soy_sauce', '간장', 'food.condiment', 'volume',
    ['샘표간장', '진간장', '양조간장', '국간장', '조선간장', '맛간장', '어간장'],
    'raw fixture: 샘표 맛간장 금S 500ml.')
add('food.condiment.gochujang_doenjang', '고추장·된장·쌈장', 'food.condiment', 'weight',
    ['고추장', '된장', '쌈장', '청정원', '순창', '해찬들', '찰고추장', '재래된장'],
    'raw fixture: 청정원 순창 찰고추장 500g.')
add('food.condiment.salt_sugar', '소금·설탕·올리고당', 'food.condiment', 'weight',
    ['소금', '굵은소금', '천일염', '정제소금', '설탕', '백설탕', '흑설탕', '황설탕', '올리고당', '자일로스'])
add('food.condiment.vinegar', '식초', 'food.condiment', 'volume',
    ['양조식초', '사과식초', '발사믹', '현미식초', '화이트식초', '흑초', '감식초'])
add('food.condiment.stock_dasida', '조미료·다시다', 'food.condiment', 'weight',
    ['다시다', '쇠고기다시다', '멸치다시다', '미원', '미풍', '치킨스톡', '야채스톡', '사골다시다'],
    'C2§4 채택: display 일반어. raw fixture: CJ 다시다 쇠고기 300g.')
add('food.condiment.broth_pack', '육수팩·티백 육수', 'food.condiment', 'pack',
    ['육수팩', '만능육수', '요리한포', 'FISH TREE', '국물팩', '디포리육수', '한팩육수'],
    'C2§1 채택: 코코달인 FISH TREE 만능육수.')
add('food.condiment.mayo_ketchup', '마요네즈·케첩·머스타드', 'food.condiment', 'weight',
    ['마요네즈', '케첩', '머스타드', '오뚜기마요', '칠리소스', '핫소스'],
    'C2§5 채택: volume→weight (마요는 g 표기 일반).')
add('food.condiment.dressing', '드레싱·소스', 'food.condiment', 'volume',
    ['오리엔탈드레싱', '시저드레싱', '발사믹드레싱', '참깨드레싱', '사우전아일랜드', '와사비', '폰즈'],
    'C2§5 notes: mixed(volume, weight).')
add('food.condiment.fish_sauce', '액젓·피쉬소스', 'food.condiment', 'volume',
    ['액젓', '멸치액젓', '까나리액젓', '피쉬소스', '남늑', 'CHIN-SU'],
    'C2§1 채택: 코코달인 CHIN-SU FOODS 남늑 피쉬소스 2L.')
add('food.condiment.meat_marinade', '고기양념 (불고기·갈비)', 'food.condiment', 'weight',
    ['갈비양념', '불고기양념', '소갈비양념', '돼지갈비양념', '백설갈비양념', 'BBQ소스'],
    'C2§1 채택: 백설 소갈비양념 840G x 2.')
add('food.condiment.curry_paste', '카레·하이라이스·짜장', 'food.condiment', 'weight',
    ['카레', '오뚜기카레', '백세카레', '하이라이스', '짜장', '짜장가루', '카레가루', '분말카레'])
add('food.condiment.red_pepper_powder', '고춧가루', 'food.condiment', 'weight',
    ['고춧가루', '청양고춧가루', '김장고춧가루', '굵은고춧가루', '고운고춧가루'],
    'C2§2 채택: spice_powder 분할 (김장 핵심).')
add('food.condiment.sesame_perilla_powder', '깨·들깨가루', 'food.condiment', 'weight',
    ['깨', '참깨', '들깨가루', '검은깨', '볶은참깨', '들깨'])
add('food.condiment.pepper_spice', '후추·향신료·허브', 'food.condiment', 'weight',
    ['후추', '통후추', '시나몬', '강황', '큐민', '오레가노', '월계수잎', '바질가루'])
add('food.condiment.oil', '식용유·기름', 'food.condiment', 'volume')
add('food.condiment.oil.cooking', '식용유 (콩·카놀라·해바라기)', 'food.condiment.oil', 'volume',
    ['콩기름', '카놀라유', '해바라기유', '옥수수유', '포도씨유', '식용유', '백설식용유'])
add('food.condiment.oil.olive', '올리브유', 'food.condiment.oil', 'volume',
    ['엑스트라버진', '올리브유', '1L올리브유', '퓨어올리브', '폼페이안', '콜라비타'],
    '홈플: simplus 엑스트라버진 올리브유 1L.')
add('food.condiment.oil.sesame_perilla', '참기름·들기름', 'food.condiment.oil', 'volume',
    ['참기름', '들기름', '오뚜기참기름', '청정원참기름', '진참기름'])

# ─── 통조림 ───
add('food.canned', '통조림·저장식품', 'food', 'weight')
add('food.canned.tuna', '참치캔', 'food.canned', 'weight',
    ['동원참치', 'sajo참치', '사조참치', '살코기참치', '라이트참치', '야채참치', '고추참치', '김치참치', '마요참치'],
    'raw fixture: 동원 라이트참치 100g.')
add('food.canned.ham', '햄·스팸캔', 'food.canned', 'weight',
    ['스팸', '런천미트', '리챔', '로스팜', '햄통조림'])
add('food.canned.fish_other', '기타 수산 통조림', 'food.canned', 'weight',
    ['고등어캔', '꽁치캔', '골뱅이', '번데기', '연어캔'])
add('food.canned.fruit_bean', '과일·콩·토마토 통조림', 'food.canned', 'weight',
    ['황도', '백도', '파인애플캔', '옥수수캔', '콩캔', '토마토홀', '토마토소스', '베이크드빈'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: beverage
# ══════════════════════════════════════════════════════════════
add('beverage', '음료', None, 'volume',
    notes='유음료(컵커피·요거트·우유)는 food.dairy. 여기는 비유제 음료.')
add('beverage.water', '생수·탄산수', 'beverage', 'volume')
add('beverage.water.still', '생수', 'beverage.water', 'volume',
    ['삼다수', '아이시스', '백산수', '평창수', '에비앙', '볼빅', '2L생수', '500ml생수'])
add('beverage.water.sparkling', '탄산수', 'beverage.water', 'volume',
    ['트레비', '씨그램', '페리에', '산펠레그리노', '탄산수', '레몬탄산수', '일화천연'])
add('beverage.soft_drink', '탄산음료', 'beverage', 'volume')
add('beverage.soft_drink.cola', '콜라', 'beverage.soft_drink', 'volume',
    ['코카콜라', '펩시', '제로콜라', '코카콜라제로', '펩시제로', '1.5L콜라', '355ml캔'],
    'raw fixture: 코카콜라 1.5L. 동일 leaf 내 1.5L vs 1.5L 비교.')
add('beverage.soft_drink.cider_lemonlime', '사이다·레몬라임', 'beverage.soft_drink', 'volume',
    ['칠성사이다', '스프라이트', '킨사이다', '세븐업', '마운틴듀'],
    'raw fixture: 롯데칠성 칠성사이다 1.5L.')
add('beverage.soft_drink.flavored_carbonated', '과즙·기타 탄산', 'beverage.soft_drink', 'volume',
    ['환타', '미린다', '닥터페퍼', '데미소다', '밀키스', '암바사'])
add('beverage.juice', '주스·과채음료', 'beverage', 'volume',
    ['오렌지주스', '사과주스', '포도주스', '토마토주스', '자몽주스', '매실주스', '알로에', '100%주스', '미닛메이드'])
add('beverage.coffee', '커피', 'beverage', 'volume')
add('beverage.coffee.instant_stick', '인스턴트·스틱 커피', 'beverage.coffee', 'count',
    ['맥심', '모카골드', '카누', '화이트골드', '카페믹스', '카누미니', '동서모카', '스틱커피'],
    'raw fixture: 동서식품 맥심 모카골드 11.7g x 100T. C2§5 notes: count + weight 보조.')
add('beverage.coffee.bean_ground', '원두·드립커피', 'beverage.coffee', 'weight',
    ['원두', '콜드브루', '드립백', '라바짜', '일리', '스타벅스원두', '디카페인'])
add('beverage.coffee.capsule', '캡슐 커피', 'beverage.coffee', 'count',
    ['네스프레소캡슐', '돌체구스토', '일리캡슐', '호환캡슐', '캡슐커피'])
add('beverage.coffee.rtd', '즉석 커피음료 (컵·캔·병)', 'beverage.coffee', 'volume',
    ['조지아', '칸타타', '레쓰비', '맥콜', 'TOP', '스타벅스병커피', '콜드브루병'],
    'C2§4 채택: "RTD" 약어 일반어로 풀어 표기.')
add('beverage.tea', '차 (티백·전통차)', 'beverage', 'count',
    ['녹차', '보리차', '옥수수차', '둥글레차', '결명자', '헛개차', '옥수수수염차', '홍차', '캐모마일', '페퍼민트', '잎차'],
    'C2§5 notes: mixed(count, weight).')
add('beverage.tea_rtd', '차 음료 (페트·캔)', 'beverage', 'volume',
    ['옥수수수염차', '17차', '헛개차', '보성녹차', '아이스티', '립톤', '데자와', '밀크티'],
    'C2§4 채택.')
add('beverage.energy_health', '에너지·이온·건강 음료', 'beverage', 'volume',
    ['박카스', '비타500', '핫식스', '레드불', '몬스터', '게토레이', '포카리스웨트', '비타민워터', '컨디션', '여명'])

# 주류 — C2§3 채택: 6→4 축소
add('beverage.alcohol', '주류', 'beverage', 'volume')
add('beverage.alcohol.beer', '맥주', 'beverage.alcohol', 'volume',
    ['카스', '테라', '하이트', '클라우드', '칭다오', '아사히', '하이네켄', '코로나', '발포주', '수제맥주', '500ml캔'])
add('beverage.alcohol.soju', '소주', 'beverage.alcohol', 'volume',
    ['참이슬', '처음처럼', '새로', '진로', '좋은데이', '한라산', '360ml소주'])
add('beverage.alcohol.wine', '와인', 'beverage.alcohol', 'volume',
    ['레드와인', '화이트와인', '로제', '스파클링', '샴페인', '카베르네', '메를로', '칠레와인', '프랑스와인'])
add('beverage.alcohol.other', '막걸리·위스키·기타 주류', 'beverage.alcohol', 'volume',
    ['장수막걸리', '국순당', '복분자주', '매실주', '청주', '백세주', '위스키', '발렌타인', '조니워커', '보드카', '진', '럼', '데킬라', '사케', '정종', '고량주'],
    'C2§3 채택: 막걸리/spirits/sake_chinese 통합 (데이터 누적 후 분할 검토).')

# ══════════════════════════════════════════════════════════════
# DOMAIN: household
# ══════════════════════════════════════════════════════════════
add('household', '생활용품', None, 'count')

add('household.paper', '화장지·티슈', 'household', 'count')
add('household.paper.toilet_tissue', '화장지 (두루마리)', 'household.paper', 'count',
    ['화장지', '두루마리화장지', '깨끗한나라', '크리넥스', '코디', '잘풀리는집', '30롤', '24롤', '3겹'],
    '코스트코: Kleenex Pure Soft Mega Rolls 40m x 60. C2§5 notes: count + length/ply metadata.')
add('household.paper.kitchen_towel', '키친타월', 'household.paper', 'count',
    ['키친타월', '잘풀리는집키친타월', '브라우니', '비바', '천연펄프', '150매', '6롤'],
    '홈플: 잘풀리는집 천연펄프 2겹 키친타월 150매*6롤. C2§5 notes: count + sheet metadata.')
add('household.paper.wet_wipes', '물티슈', 'household.paper', 'count',
    ['물티슈', '캡형물티슈', '휴대용물티슈', '에코', '순둥이', '알콜물티슈'])
add('household.paper.facial_tissue', '미용티슈·각티슈', 'household.paper', 'count',
    ['각티슈', '미용티슈', '크리넥스', '페이셜티슈', '데코소프트'])

add('household.laundry', '세탁·섬유', 'household', 'volume')
add('household.laundry.detergent_liquid', '액체 세제', 'household.laundry', 'volume',
    ['액체세제', '다우니', '퍼실', '테크', '비트', '액츠', '한방세제', '드럼세탁기', '세탁세제'])
add('household.laundry.detergent_pod', '세탁 캡슐', 'household.laundry', 'count',
    ['세탁캡슐', '타이드팟', '비트캡슐', '퍼실디스크', '세제캡슐'],
    'C2§5 채택: pod와 powder 분리.')
add('household.laundry.detergent_powder', '가루 세제', 'household.laundry', 'weight',
    ['가루세제', '한스푼', '세제블록', '한방가루세제'])
add('household.laundry.softener', '섬유유연제', 'household.laundry', 'volume',
    ['다우니', '샤프란', '피죤', '섬유유연제', '향기지속', '다우니인텐스'])
add('household.laundry.bleach_stain', '표백·얼룩제거', 'household.laundry', 'volume',
    ['옥시크린', '락스', '표백제', '얼룩제거제', '살균표백', '산소표백'])

add('household.dish', '주방세제·수세미', 'household', 'volume')
add('household.dish.dishwash_liquid', '주방세제', 'household.dish', 'volume',
    ['퐁퐁', '트리오', '자연퐁', '참그린', '주방세제', '식기세제'])
add('household.dish.dishwasher_tab', '식기세척기 세제', 'household.dish', 'count',
    ['피니쉬', '칼곤', '식기세척기세제', '디시워셔', '린스', '소금'])
add('household.dish.sponge_glove_cloth', '수세미·고무장갑·행주', 'household.dish', 'count',
    ['수세미', '3M', '스카치브라이트', '고무장갑', '행주', '면행주', '극세사행주'],
    'C2§4 채택: display에 행주 명시.')

add('household.cleaning', '청소·살균', 'household', 'volume')
add('household.cleaning.bathroom', '욕실 청소', 'household.cleaning', 'volume',
    ['욕실세정제', '변기세정제', '락스', '곰팡이제거제', '칙칙이', '욕실청소'])
add('household.cleaning.kitchen_general', '주방·다목적 세정제', 'household.cleaning', 'volume',
    ['주방세정제', '가스레인지세정제', '다목적세정제', '매직블럭', '멀티클리너'])
add('household.cleaning.floor_glass', '바닥·유리 세정제', 'household.cleaning', 'volume',
    ['바닥청소', '유리세정제', '글라스클리너', '마룻바닥'])
add('household.cleaning.air_freshener', '방향·탈취제', 'household.cleaning', 'volume',
    ['페브리즈', '방향제', '디퓨저', '탈취제', '차량용방향제', '화장실방향제'])
add('household.cleaning.insecticide', '살충·방충', 'household.cleaning', 'volume',
    ['홈매트', '모기약', '에프킬라', '바퀴벌레약', '개미약', '살충제', '좀약', '훈증기'],
    'C2§5 notes: mixed (스프레이 volume / 매트·좀약 count).')
add('household.cleaning.tool', '청소 도구', 'household.cleaning', 'count',
    ['밀대', '빗자루', '청소포', '물걸레', '마대', '청소솔', '먼지털이', '정전기청소포'])

add('household.wrap_foil_bag', '랩·호일·지퍼백', 'household', 'count',
    ['지퍼백', '위생장갑', '종이호일', '비닐랩', '알루미늄호일', '진공팩'],
    'C2§2 채택: storage 분할.')
add('household.food_container', '밀폐용기·보관용기', 'household', 'count',
    ['락앤락', '보관용기', '밀폐용기', '일회용용기'],
    'C2§2·§6 채택. home.storage_container와 의미 중복이라 본 leaf로 통합 사용.')
add('household.disposable', '일회용품 (컵·접시·수저)', 'household', 'count',
    ['종이컵', '빨대', '일회용접시', '나무젓가락', '일회용수저'])
add('household.trash_bag', '쓰레기봉투·종량제', 'household', 'count',
    ['쓰레기봉투', '종량제봉투', '음식물봉투', '재활용봉투', '50L', '20L'],
    'C2§1 채택: disposable에서 독립.')

add('household.electrical', '건전지·전구·전기용품', 'household', 'count',
    ['건전지', 'AA', 'AAA', '듀라셀', '에너자이저', 'LED전구', '형광등', '충전지', '멀티탭', '연장선', '콘센트'],
    'C2§1·§6 채택: 멀티탭을 digital.accessory에서 이쪽으로. 일반 마트 전기소모품 매대 멘탈 모델.')
add('household.candle_match', '양초·라이터', 'household', 'count',
    ['양초', '향초', '캔들', '라이터', '성냥', '가스충전'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: beauty
# ══════════════════════════════════════════════════════════════
add('beauty', '뷰티', None, 'volume')
add('beauty.skincare', '스킨케어', 'beauty', 'volume')
add('beauty.skincare.cleanser', '클렌저·폼클렌징', 'beauty.skincare', 'volume',
    ['클렌징폼', '폼클렌징', '클렌징오일', '클렌징워터', '립앤아이리무버', '세안제', '비누클렌저'])
add('beauty.skincare.toner_essence', '토너·에센스·세럼', 'beauty.skincare', 'volume',
    ['토너', '스킨', '에센스', '세럼', '부스터', '미스트', '앰플'])
add('beauty.skincare.lotion_cream', '로션·크림', 'beauty.skincare', 'volume',
    ['로션', '수분크림', '영양크림', '나이트크림', '아이크림', '안티에이징', '데일리크림'])
add('beauty.skincare.sunscreen', '자외선차단제', 'beauty.skincare', 'volume',
    ['선크림', '선스틱', '선쿠션', 'SPF50', '자외선차단', '톤업선크림', '무기자차'])
add('beauty.skincare.mask_sheet', '마스크팩', 'beauty.skincare', 'count',
    ['마스크팩', '시트마스크', '메디힐', '닥터자르트', '모델링팩', '슬리핑팩', '모공팩'])
add('beauty.skincare.body_lotion', '바디로션·바디크림', 'beauty.skincare', 'volume',
    ['바디로션', '바디크림', '바디버터', '바디오일', '비오더마', '아토팜', '세타필'],
    '코스트코: Bioderma Atoderm Ultra Cream 500ml x 2.')
add('beauty.skincare.hand_lip', '핸드크림·립밤', 'beauty.skincare', 'volume',
    ['핸드크림', '립밤', '립케어', '발크림', '큐티클', '록시땅', '키엘'])

add('beauty.haircare', '헤어케어', 'beauty', 'volume')
add('beauty.haircare.shampoo', '샴푸', 'beauty.haircare', 'volume',
    ['샴푸', '두피샴푸', '탈모샴푸', '미장센', '려', '케라시스', '헤드앤숄더', '팬틴', '도브'])
add('beauty.haircare.conditioner_treatment', '린스·트리트먼트', 'beauty.haircare', 'volume',
    ['린스', '컨디셔너', '트리트먼트', '헤어팩', '모발영양제'])
add('beauty.haircare.styling', '헤어 스타일링·염색', 'beauty.haircare', 'volume',
    ['헤어왁스', '무스', '헤어스프레이', '헤어에센스', '헤어오일', '염색약', '새치커버'])

add('beauty.bath_body', '바디워시·비누·입욕제', 'beauty', 'volume',
    ['바디워시', '샤워젤', '비누', '세안비누', '도브', '다이알', '해피바스', '입욕제', '거품목욕'])

add('beauty.oral', '구강용품', 'beauty', 'count')
add('beauty.oral.toothpaste', '치약', 'beauty.oral', 'volume',
    ['치약', '페리오', '메디안', '죽염', '시린메드', '클리어덴트', '미백치약', '어린이치약'])
add('beauty.oral.toothbrush', '칫솔·치실·치간', 'beauty.oral', 'count',
    ['칫솔', '전동칫솔', '치실', '치간칫솔', '오랄비', '필립스'])
add('beauty.oral.mouthwash', '가글·구강청결제', 'beauty.oral', 'volume',
    ['가그린', '리스테린', '가글', '구강청결제', '구취제거'])

add('beauty.makeup', '색조 메이크업 (전체)', 'beauty', 'count',
    ['립스틱', '틴트', '쿠션', '파운데이션', '파우더', '아이섀도우', '마스카라', '아이라이너', '블러셔', '컨실러'],
    'C2§2 검토: 마트 색조 데이터 부족하여 분할 보류 (1차는 단일 leaf).')

add('beauty.perfume', '향수·바디미스트', 'beauty', 'volume',
    ['향수', '오드퍼퓸', '오드뚜왈렛', '바디미스트', '코롱', '디올', '샤넬'])
add('beauty.shaving', '면도용품', 'beauty', 'count',
    ['면도기', '면도날', '질레트', '쉬크', '면도크림', '애프터쉐이브', '일회용면도기'])
add('beauty.feminine_care', '여성위생용품', 'beauty', 'count',
    ['생리대', '위스퍼', '좋은느낌', '라엘', '탐폰', '팬티라이너', '오버나이트', '한방생리대'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: health
# ══════════════════════════════════════════════════════════════
add('health', '건강·헬스', None, 'count')
add('health.supplement', '건강기능식품', 'health', 'count')
add('health.supplement.vitamin', '비타민·미네랄', 'health.supplement', 'count',
    ['비타민C', '비타민D', '종합비타민', '멀티비타민', '마그네슘', '칼슘', '아연', '임팩타뮨'],
    '코스트코: Daewoong Pharm Impactamune 84ct.')
add('health.supplement.probiotic', '유산균·프로바이오틱스', 'health.supplement', 'count',
    ['유산균', '프로바이오틱스', '락토핏', '듀오락', '정장제'])
add('health.supplement.ginseng', '홍삼·인삼', 'health.supplement', 'count',
    ['정관장', '홍삼', '홍삼정', '홍삼스틱', '인삼', '산삼', '에브리타임'])
add('health.supplement.other', '오메가3·콜라겐·관절·다이어트', 'health.supplement', 'count',
    ['오메가3', '루테인', 'EPA', 'DHA', '콜라겐', '저분자콜라겐', '히알루론산', '글루코사민', 'MSM', '가르시니아', '단백질보충제'],
    'C2§3 채택: omega/collagen/joint/diet 통합 (데이터 누적 후 분할 검토).')
add('health.medical', '의약외품·구급', 'health', 'count',
    ['마스크', 'KF94', '손소독제', '밴드', '거즈', '파스', '일회용밴드', '체온계'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: baby
# ══════════════════════════════════════════════════════════════
add('baby', '육아·유아', None, 'count')
add('baby.diaper', '기저귀', 'baby', 'count',
    ['기저귀', '팬티기저귀', '하기스', '마미포코', '군기저귀', '보솜이', '신생아기저귀', '대형기저귀'])
add('baby.wipe', '아기 물티슈', 'baby', 'count',
    ['아기물티슈', '베베숲', '순둥이', '캡형물티슈', '휴대용물티슈'])
add('baby.formula', '분유', 'baby', 'weight',
    ['분유', '임페리얼', '매일분유', '남양분유', '산양분유', '1단계', '2단계', '압타밀'])
add('baby.snack_meal', '이유식·아기간식', 'baby', 'count',
    ['이유식', '아기과자', '떡뻥', '아기치즈', '베이비푸드', '아이밀', '베베쿡'],
    'C2§5 notes: mixed (파우치/병/과자 g·ml·count 혼재).')
add('baby.baby_care', '아기 스킨·목욕', 'baby', 'volume',
    ['아기로션', '아기샴푸', '아기바디워시', '아토팜', '베이비스킨', '아기파우더'])
add('baby.kids_toy_book', '유아동 완구·도서·아동용품', 'baby', 'count',
    ['완구', '장난감', '블록', '레고', '아동도서', '그림책', '아동의류', '카시트', '유아책상'],
    'C2§1 P0 채택: 코스트코 BabyKids endpoint kids 영역 흡수.')

# ══════════════════════════════════════════════════════════════
# DOMAIN: pet
# ══════════════════════════════════════════════════════════════
add('pet', '반려동물', None, 'weight')
add('pet.dog_food', '강아지 사료·간식', 'pet', 'weight',
    ['강아지사료', '로얄캐닌', '시저', '페디그리', '강아지간식', '육포', '덴탈껌'])
add('pet.cat_food', '고양이 사료·캔·츄르', 'pet', 'weight',
    ['고양이사료', '고양이캔', '츄르', '키캣', '위스카스', '캣츠비', '헤어볼'])
add('pet.litter', '고양이 모래', 'pet', 'weight',
    ['고양이모래', '벤토나이트', '두부모래', '응고형모래', '실리카모래'],
    'C2§5 채택: litter_supplies 분리.')
add('pet.supplies', '배변패드·하네스·캣타워', 'pet', 'count',
    ['펫매트', '배변패드', '산책줄', '하네스', '캣타워', '스크래쳐', '장난감'])
add('pet.grooming', '펫 샴푸·미용용품', 'pet', 'volume',
    ['펫샴푸', '펫컨디셔너', '귀세정제', '발세정제', '치약'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: home
# ══════════════════════════════════════════════════════════════
add('home', '가정·주방용품', None, 'count')
add('home.cookware', '냄비·프라이팬', 'home', 'count',
    ['프라이팬', '냄비', '압력솥', '웍', '그릴팬', '테팔', '키친아트', '통3중냄비'])
add('home.kitchen_tool', '조리도구', 'home', 'count',
    ['도마', '칼', '주방가위', '국자', '뒤집개', '거품기', '채반', '계량컵', '강판'])
add('home.tableware', '식기·수저·컵', 'home', 'count',
    ['그릇', '접시', '수저세트', '컵', '머그컵', '와인잔', '텀블러', '도자기', '본차이나'])
add('home.bedding', '침구·홈패브릭', 'home', 'count',
    ['이불', '베개', '매트리스토퍼', '침대커버', '담요', '극세사', '거위털', '호텔식이불'])
add('home.furniture', '가구', 'home', 'count',
    ['소파', '책상', '의자', '식탁', '책장', '서랍장', '옷장', '침대프레임', '매트리스', '수납장'],
    'C2§1·§7 P0 채택: 코스트코 Furniture endpoint.')
add('home.tool_diy', '공구·DIY', 'home', 'count',
    ['드라이버', '망치', '줄자', '공구세트', '스탠리', '사다리', '작업장갑', '전동드릴'],
    'C2§4 채택: 운반(카트)은 별 leaf.')
add('home.cart_carrier', '카트·운반용품', 'home', 'count',
    ['핸드트럭', '카트', '쇼핑카트', '접이식카트', '장바구니카트'],
    'C2§4 채택: 코스트코 Stanley Folding Hand Truck 흡수.')

# ══════════════════════════════════════════════════════════════
# DOMAIN: appliance
# ══════════════════════════════════════════════════════════════
add('appliance', '가전', None, 'count')
add('appliance.large_home', '대형가전 (냉장고·세탁기·에어컨)', 'appliance', 'count',
    ['냉장고', '양문형', '4도어', '김치냉장고', '세탁기', '드럼세탁기', '건조기', '워시타워', '에어컨', '스탠드형', '벽걸이', '히터'],
    'C2§3 채택: refrigerator/washer/aircon 통합 (마트 데이터 부족).')
add('appliance.large_av', 'TV·영상', 'appliance', 'count',
    ['TV', 'OLED', 'QLED', '4K', '8K', '사운드바', '빔프로젝터', '셋톱박스'])
add('appliance.kitchen', '주방가전', 'appliance', 'count')
add('appliance.kitchen.cooker', '밥솥·전기레인지·인덕션', 'appliance.kitchen', 'count',
    ['전기밥솥', '쿠쿠', '쿠첸', '압력밥솥', '인덕션', '전기레인지', '하이라이트'])
add('appliance.kitchen.microwave_oven', '전자레인지·오븐·에어프라이어', 'appliance.kitchen', 'count',
    ['전자레인지', '오븐', '광파오븐', '컨벡션', '토스터', '에어프라이어'])
add('appliance.kitchen.small', '믹서·커피머신·정수기·식기세척기', 'appliance.kitchen', 'count',
    ['믹서기', '블렌더', '커피머신', '토스터', '전기포트', '식기세척기', '정수기', '와플메이커'])
add('appliance.living', '생활가전', 'appliance', 'count')
add('appliance.living.vacuum', '청소기', 'appliance.living', 'count',
    ['청소기', '무선청소기', '로봇청소기', '다이슨', 'LG코드제로', '차이슨'])
add('appliance.living.air_care', '공기청정기·가습기·제습기', 'appliance.living', 'count',
    ['공기청정기', '가습기', '제습기', '위닉스', '코웨이', '다이슨', '샤오미'])
add('appliance.living.beauty_appliance', '뷰티·이미용 가전', 'appliance.living', 'count',
    ['드라이기', '고데기', '매직기', '다이슨에어랩', '전동면도기', '이발기'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: digital
# ══════════════════════════════════════════════════════════════
add('digital', '디지털·IT', None, 'count')
add('digital.mobile', '모바일·태블릿·웨어러블', 'digital', 'count',
    ['스마트폰', '아이폰', '갤럭시', '태블릿', '아이패드', '갤럭시탭', '스마트워치', '갤럭시워치', '애플워치'])
add('digital.computer', '컴퓨터·노트북·주변부품', 'digital', 'count',
    ['노트북', '데스크탑', '맥북', '그램', '모니터', 'SSD', 'HDD', '그래픽카드', '메인보드', 'CPU'])
add('digital.audio', '음향·이어폰', 'digital', 'count',
    ['이어폰', '헤드폰', '무선이어폰', '에어팟', '버즈', '블루투스스피커', '사운드바'])
add('digital.charger_cable', '충전기·케이블·보조배터리', 'digital', 'count',
    ['보조배터리', '충전기', 'USB허브', '케이블', '고속충전기', '맥세이프', '거치대', '폰케이스'],
    'C2§2 채택: accessory 분할. 멀티탭은 household.electrical로 이관.')
add('digital.pc_peripheral', 'PC 주변기기 (키보드·마우스)', 'digital', 'count',
    ['키보드', '마우스', '게이밍키보드', '게이밍마우스', '마우스패드', '웹캠', '헤드셋'])
add('digital.game', '게임·소프트웨어·기프트카드', 'digital', 'count',
    ['닌텐도', '플레이스테이션', 'PS5', '엑스박스', '게임패드', '게임소프트', '스팀', '기프트카드'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: fashion
# ══════════════════════════════════════════════════════════════
add('fashion', '의류·잡화', None, 'count',
    notes='마트 PB·잡화 한정. 본격 패션은 RD8 범위 외.')
add('fashion.socks_stocking', '양말·스타킹·레깅스', 'fashion', 'count',
    ['양말', '발목양말', '스니커즈양말', '게스양말', '중목양말', '6족양말', '스타킹', '레깅스', '타이즈'],
    'C2§3 채택: innerwear 3leaf→통합. 홈플 게스 중목 6족 양말.')
add('fashion.underwear', '속옷·이너웨어', 'fashion', 'count',
    ['팬티', '브라', '트렁크', '드로즈', 'BYC', '트라이', '보디가드', '이너웨어'])
add('fashion.basic_apparel', '기본 의류 (티·잠옷·홈웨어)', 'fashion', 'count',
    ['반팔티', '긴팔티', '잠옷', '홈웨어', '트레이닝복', '후리스', '패딩조끼'])
add('fashion.bag_accessory', '가방·우산·모자·잡화', 'fashion', 'count',
    ['장바구니', '에코백', '보조가방', '지갑', '우산', '모자', '캠핑가방'])
add('fashion.footwear', '신발·실내화·슬리퍼', 'fashion', 'count',
    ['슬리퍼', '실내화', '욕실화', '운동화', '장화', '아쿠아슈즈', '쪼리'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: outdoor
# ══════════════════════════════════════════════════════════════
add('outdoor', '레저·스포츠', None, 'count')
add('outdoor.camping', '캠핑용품', 'outdoor', 'count',
    ['텐트', '침낭', '캠핑의자', '캠핑테이블', '코펠', '버너', '부탄가스', '캠핑그릴', '아이스박스', '캠핑랜턴'])
add('outdoor.sport_fitness', '운동·피트니스·구기·자전거', 'outdoor', 'count',
    ['요가매트', '덤벨', '폼롤러', '단백질쉐이커', '줄넘기', '풀업바', '헬스장갑', '축구공', '농구공', '배드민턴', '골프공', '골프장갑', '자전거', '헬멧'],
    'C2§3 채택: fitness + sport_ball 통합.')

# ══════════════════════════════════════════════════════════════
# DOMAIN: automotive (C2§6 채택: home.auto에서 독립)
# ══════════════════════════════════════════════════════════════
add('automotive', '자동차용품', None, 'count',
    ['엔진오일', '워셔액', '차량용방향제', '와이퍼', '트렁크매트', '차량용청소기', '부동액', '세차용품'],
    'C2§6 채택: home.auto→독립 root. 코스트코 Automotive endpoint.')

# ══════════════════════════════════════════════════════════════
# DOMAIN: office
# ══════════════════════════════════════════════════════════════
add('office', '사무·문구', None, 'count',
    ['볼펜', '형광펜', '노트', 'A4용지', '포스트잇', '파일', '클립', '사무용가위', '풀', '테이프'])

# ══════════════════════════════════════════════════════════════
# DOMAIN: gift (C2§2 P0 채택: 분할)
# ══════════════════════════════════════════════════════════════
add('gift', '상품권·선물세트', None, 'count',
    notes='C2§2 P0 채택: 단일 leaf에서 root + 4children으로 확장.')
add('gift.voucher', '상품권·기프티콘', 'gift', 'count',
    ['상품권', '기프티콘', '백화점상품권', '문화상품권', '모바일상품권'])
add('gift.food_set', '식품 선물세트 (한우·과일·홍삼식품)', 'gift', 'count',
    ['한우선물세트', '과일선물세트', '굴비선물세트', '명절선물', '추석선물', '설선물', '참치선물세트', '스팸선물세트'])
add('gift.health_set', '건강 선물세트 (정관장 등)', 'gift', 'count',
    ['정관장선물세트', '홍삼선물세트', '비타민선물', '건강기능식품선물'])
add('gift.household_set', '생활 선물세트 (샴푸·세제·치약 세트)', 'gift', 'count',
    ['샴푸선물세트', '치약세트', '비누선물세트', '세제선물세트', 'LG생활건강선물'])


# ─────────────────────────────────────────────────────────────────────
# 검증
# ─────────────────────────────────────────────────────────────────────
def validate(nodes):
    errors = []
    ids = [n['id'] for n in nodes]
    dups = [k for k, v in Counter(ids).items() if v > 1]
    if dups:
        errors.append(f"중복 id: {dups}")
    idset = set(ids)
    for n in nodes:
        p = n['parent']
        if p is not None and p not in idset:
            errors.append(f"parent 누락: {n['id']} -> {p}")
        if not re.match(r'^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$', n['id']):
            errors.append(f"id 형식 위반: {n['id']}")
        if n['unit_kind_default'] not in ('weight', 'volume', 'count', 'pack'):
            errors.append(f"unit_kind_default 오류: {n['id']}={n['unit_kind_default']}")
    # leaf = 자식 없는 노드. leaf에 keyword_seeds >=3 필수
    children = Counter([n['parent'] for n in nodes if n['parent']])
    leaves = [n for n in nodes if children.get(n['id'], 0) == 0]
    for n in leaves:
        if len(n['keyword_seeds']) < 3:
            errors.append(f"leaf keyword_seeds<3: {n['id']} ({len(n['keyword_seeds'])})")
    return errors, leaves


# ─────────────────────────────────────────────────────────────────────
# 실 raw 데이터 매핑 시뮬레이션
# ─────────────────────────────────────────────────────────────────────
def collect_raw_names():
    files = glob.glob(r'E:\pdf\capston01\artifacts\exports\raw-batch\**\raw_products.jsonl', recursive=True)
    names = set()
    for f in files:
        try:
            for line in open(f, encoding='utf-8'):
                d = json.loads(line)
                n = (d.get('name') or '').strip()
                if n:
                    names.add(n)
        except Exception:
            continue
    return sorted(names)


def map_name_to_leaf(name, leaves):
    """간단 키워드 매칭. 매칭된 모든 leaf 중 keyword 최장 일치 leaf 1개 선택."""
    best = None
    best_len = 0
    for leaf in leaves:
        for kw in leaf['keyword_seeds']:
            if kw and kw in name:
                if len(kw) > best_len:
                    best_len = len(kw)
                    best = leaf['id']
    return best


def write_yaml(nodes, path):
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write("# WalletSavior RD8 카테고리 트리 (C3 최종, opus+gpt5.5 통합)\n")
        f.write("# 생성기: docs/RD8/_build_categories_rd8.py\n")
        f.write("# 필드: id, display_name_ko, parent, unit_kind_default, keyword_seeds, notes\n")
        f.write("# unit_kind_default: weight | volume | count | pack\n")
        f.write("# parent: null 이면 도메인 루트\n")
        f.write("# id 정책: 영문 snake_case 세그먼트를 점(.)으로 네임스페이스 (C1 호환)\n\n")
        f.write("categories:\n")
        for n in nodes:
            f.write(f"  - id: {n['id']}\n")
            # 한글 문자열은 quoting
            name = n['display_name_ko'].replace('"', '\\"')
            f.write(f'    display_name_ko: "{name}"\n')
            if n['parent'] is None:
                f.write(f"    parent: null\n")
            else:
                f.write(f"    parent: {n['parent']}\n")
            f.write(f"    unit_kind_default: {n['unit_kind_default']}\n")
            if n['keyword_seeds']:
                seeds = ', '.join(f'"{s}"' for s in n['keyword_seeds'])
                f.write(f"    keyword_seeds: [{seeds}]\n")
            else:
                f.write(f"    keyword_seeds: []\n")
            if n['notes']:
                notes = n['notes'].replace('"', '\\"')
                f.write(f'    notes: "{notes}"\n')
            f.write("\n")


if __name__ == '__main__':
    out_path = r'E:\pdf\capston01\packages\shared\data\categories_rd8.yaml'
    write_yaml(N, out_path)
    print(f"[OK] wrote {out_path} (nodes={len(N)})")

    errors, leaves = validate(N)
    print(f"[VAL] leaves={len(leaves)}, errors={len(errors)}")
    for e in errors:
        print("  -", e)

    # yaml 파싱 검증
    try:
        import yaml as _y
        data = _y.safe_load(open(out_path, encoding='utf-8'))
        n = len(data.get('categories', []))
        print(f"[YAML] safe_load OK, categories={n}")
    except Exception as e:
        print(f"[YAML] FAIL {e}")

    # 실 raw 매핑 시뮬레이션
    names = collect_raw_names()
    print(f"\n[RAW] distinct names={len(names)}")
    mapped = []
    unmapped = []
    for nm in names:
        leaf = map_name_to_leaf(nm, leaves)
        if leaf:
            mapped.append((nm, leaf))
        else:
            unmapped.append(nm)
    print(f"[RAW] mapped={len(mapped)} unmapped={len(unmapped)}")
    print("\n--- 매핑 샘플 ---")
    for nm, lf in mapped:
        print(f"  {nm!r} -> {lf}")
    if unmapped:
        print("\n--- 미매핑 ---")
        for nm in unmapped:
            print(f"  {nm!r}")
