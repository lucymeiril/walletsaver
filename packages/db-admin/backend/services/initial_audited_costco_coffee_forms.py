"""Exact food forms in Costco's coffee shelf; equipment and gifts excluded."""
from urllib.parse import urlparse
GROUPS={
 'food.drinks.coffee.ready': ('칸타타 콘트라베이스 디카페인 커피 500ml x 18','스타벅스 커피 크래프트 리치 블랙 260ml x 3','스타벅스 커피 크래프트 시그니처캐러멜향 260ml x 3'),
 'food.drinks.coffee.drip': ('룰리커피 스페셜티 드립백 10g x 30',),
 'food.drinks.tea.black': ('커피빈 얼그레이 바닐라라떼 25g x 40ct',),
 'food.drinks.tea.grain': ('오르조 바닐라라떼15g x 50','펄세스 스테비아 율무차 18g x 100ct',),
 'food.bakery.dessert.cake': ('Emmi 이탈리안티라미수컵85g x 6',),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}
BEAN_TITLES=frozenset(('커피명가 올굿블렌드 1.13kg','테라로사 올데이 블렌드 1.13kg'))


def reviewed_costco_coffee_form_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('커피',):
        return None
    title=evidence['source_title']
    if title in BEAN_TITLES and any(urlparse(url).hostname in {'costco.co.kr','www.costco.co.kr'} and '/Whole-BeansGround-Coffee/' in url for url in evidence.get('source_urls',())):
        return 'food.drinks.coffee.beans'
    return TITLES.get(title)
