"""Exact forms in polluted egg shelf; ambiguous beef cuts need URL evidence."""
import re
from urllib.parse import urlparse

GROUPS={
 'food.meat.eggs.chicken': ('한스팜 유기농계란15ea x 2','한스팜 자연을품은동물복지란20ea x 2','풀무원 동물복지란 60 구 (30ea x 2)'),
 'food.meat.fresh.beef': ('한우 1++(9) 냉장 등심 로스 170g X 4팩','1등급 한우 불고기 2kg','1등급 한우불고기 2kg x 2ea','호주산 냉장 와규 윗등심살 로스 300g x 4팩','호주산 냉장 와규 부채살 로스 300g x 4팩','호주산 와규 치마살 로스 300g x 4팩'),
 'food.meat.fresh.pork': ('국내산 냉동 돈육 한입 삼겹살 (1.0kg x 2)','포크밸리숯불구이용 삼겹살( 1.0kg X 2 )','포크밸리숯불구이용 목심( 1.0kg X 2 )'),
 'food.meals.prepared.seasoned_meat': ('호주산 양념 소불고기 2.7kg','호주산 양념 LA 갈비2.5kg x 2팩','미국산 돈육고추장불고기 600g x 4팩','미국산 돈육고추장불고기2.5kg x 2팩','미국산 돈육 양념 칼집구이 600g x 4팩','미국산 돈육 양념 칼집구이 2.5kg x 2팩','국내산 양념 돼지갈비 2.9kg x 2팩','미국산 부채살 양념 칼집구이 600g X 4'),
 'food.meals.noodles.udon': ('백제 가마타마우동 216g x 6',),
 'food.seasonings.pastes.soy': ('샘표 계란 간장200ml x 4',),
 'food.seasonings.stock.chicken': ('소스락 치킨스톡 3g x 80 / 최소구매 2',),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}
URL_BEEF_TITLES=frozenset((
 '호주산 냉장 안창살 로스 500g x 4팩','호주산 냉장 안심 스테이크 200g x 6팩',
 '호주산 냉장 살치살 로스 500g X 3팩','호주산 척아이롤 국거리 300g x 4팩',
 '호주산 냉장 갈비살 로스 500g x 4팩','호주산 냉장 부채살 로스 500g x 4팩',
 '미국산 냉동 차돌박이 1.3kg x 2팩','호주산 냉장 채끝 스테이크 350g X 4팩',
 '호주산 냉장 토시살 로스 500g x 4팩','호주산 냉장 치마살 로스 500g x 4팩',
 '호주산 냉장 등심 스테이크 300g x 4팩','호주산 냉장 꽃갈비살 로스 500g x 3팩',
 '미국산 냉동 척아이롤 1.5kg x 2팩',
))


def reviewed_costco_egg_meat_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('계란',):
        return None
    title=evidence['source_title']
    if title in TITLES:
        return TITLES[title]
    if title in URL_BEEF_TITLES:
        for url in evidence.get('source_urls',()):
            parsed=urlparse(url)
            if parsed.hostname in {'www.costco.co.kr','costco.co.kr'} and re.search(r'\bbeef\b',parsed.path,re.I):
                return 'food.meat.fresh.beef'
    return None
