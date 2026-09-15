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
URL_ENTRIES={
 '일리 E.S.E. 파드 커피 번들팩 54EA (18EA x3팩)': ('food.drinks.coffee.pod','/illy-ESE-POD-Coffee-Bundle-Pack-54EA18EA-x3PK/'),
 '루카스나인 우베라떼 18g x 50': ('food.drinks.coffee.mix','/Lookas9-Ube-Latte-18g-x-50/'),
 '립톤제로 복숭아 500ml x 18': ('food.drinks.tea.ready','/Lipton-Peach-Ice-Tea-500ml-x-18/'),
 '이디야 토피넛라떼 20g x 50입': ('food.drinks.coffee.mix','/Ediya-Coffee-Toffee-Nut-Latte-20g-x-50ct/'),
 '커피빈 피스타치오라떼 26g x 30ct': ('food.drinks.coffee.mix','/Coffee-Bean-Pistachio-Latte-26g-x-30ct/'),
}


def reviewed_costco_coffee_form_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('커피',):
        return None
    title=evidence['source_title']
    entry=URL_ENTRIES.get(title)
    if entry:
        leaf,marker=entry
        if any(urlparse(url).hostname in {'costco.co.kr','www.costco.co.kr'} and marker in urlparse(url).path for url in evidence.get('source_urls',())):
            return leaf
    if title in BEAN_TITLES and any(urlparse(url).hostname in {'costco.co.kr','www.costco.co.kr'} and '/Whole-BeansGround-Coffee/' in url for url in evidence.get('source_urls',())):
        return 'food.drinks.coffee.beans'
    return TITLES.get(title)
