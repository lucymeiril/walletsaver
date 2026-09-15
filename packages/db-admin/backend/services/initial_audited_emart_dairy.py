"""Exact dairy forms from Emart's broad milk/dairy shelf."""
GROUPS={
 'food.dairy.cheese.sliced': ('[쓱7클럽] 소와나무 체다치즈 270g','[매일유업] 상하치즈 뼈로가는 칼슘치즈 270g','드빈치 자연방목치즈30입 기획'),
 'food.dairy.cheese.portion': ('앙팡치즈 까요까요 플레인 72g','앙팡치즈 까요까요 딸기 72g','치즈큐빅 파티 플레인87g','치즈큐빅파티 플레인87g*2입기획'),
 'food.dairy.yogurt.drink': ('[한국야쿠르트]메치니코프플레인사과 140mlX4','hy 메치니코프 오곡씨리얼 140ml*4','[한국야쿠르트]메치니코프플레인 140mlX4','윌 오리지날 150mlX5개','[매일유업] 엔요 10입 기획(100ml*10)','이오 15입(80ml*15)','거꾸로먹는 야쿠르트 (110ml*4입)','윌 저지방 150mlX5개','피로케어 쿠퍼스 140mlX4개','딸기 담은 요구르트 750ml'),
 'food.dairy.yogurt.greek': ('[매일유업] 바이오 그릭 딜라이트 무가당 플레인 8본 (80G*8)',),
 'food.dairy.yogurt.squeeze': ('짜요짜요 딸기맛 240g',),
 'food.dairy.yogurt.topping': ('비요뜨 초코링 (138g*2개)','비요뜨 크런치볼 (138g*2개)'),
 'food.dairy.yogurt.spoon': ('더 진한 순수 플레인 요거트 1.8L','에이 클래스 저지방요거트 900g','요플레 클래식 플레인 (85g4개)','유기농 베이비 요구르트 플레인 340g (85g*4)','다논 하루요거트플레인 80g*4'),
 'food.dairy.milk.plain': ('[매일유업] 매일우유 오리지널 후레쉬팩 900ML*2','목장의 신선함이 살아 있는 저지방 1L'),
 'food.dairy.milk.coffee': ('커피포리 200ml* 4입',),
 'food.dairy.milk.banana': ('바나나 스페셜(240ml*6개) 1440ml',),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}


def reviewed_emart_dairy_leaf(evidence):
    if evidence['mart']!='emart' or tuple(evidence['source_path_parts'])!=('우유/유제품',): return None
    return TITLES.get(evidence['source_title'])
