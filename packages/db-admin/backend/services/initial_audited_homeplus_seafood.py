"""Hand-reviewed Homeplus seafood identities, not wholesale shelf copying.

Only exact titles and complete recorded paths are accepted. Sauces, unspecified
seafood mixes, variable-weight counter sales and approximate gift weights stay
pending. Quantity/promotion and contradictory category evidence remain separate
blocking contracts.
"""

ROOT = '수산물/건어물'
FROZEN = (ROOT, '간편/냉동수산물', '냉동간편수산물', '냉동선어')
SQUID = (ROOT, '건오징어/건어물/다시팩', '건오징어/한치/진미채', '조미오징어')
POLL = (ROOT, '건오징어/건어물/다시팩', '노가리/황태/먹태', '노가리/황태')
DRIED_SHRIMP = (ROOT, '건오징어/건어물/다시팩', '멸치/새우', '건새우')
LAVER = (ROOT, '김/미역/기타해조류', '김/김자반/부각')
MOLLUSCS = (ROOT, '연체갑각류', '오징어/낙지/주꾸미/문어')

# leaf -> (full path, literal titles) groups; no substring or guessed alias.
GROUPS = {
 'food.seafood.fish.mackerel': ((FROZEN, ('손질 제주 고등어 500G(팩)', '손질 노르웨이 고등어필렛 500G(봉)')),),
 'food.seafood.fish.spanish_mackerel': ((FROZEN, ('손질 제주 삼치 500G(팩)',)),),
 'food.seafood.fish.hairtail': ((FROZEN, ('손질 제주 갈치 400G(팩)',)),),
 'food.seafood.fish.pollock': ((FROZEN, ('손질 수제 동태살 500G(팩)',)),),
 'food.seafood.fish.cod': ((FROZEN, ('손질 수제 대구살 350G(팩)',)),),
 'food.seafood.fish.eel': (((ROOT,'생선','구색선어/회','구색선어'), ('자포니카 민물장어 500G (박스/국산/실중량)',)),),
 'food.seafood.molluscs.squid': (((ROOT,'간편/냉동수산물','냉동간편수산물','냉동새우'), ('손질 오징어링 500G(팩)',)),),
 'food.seafood.molluscs.webfoot_octopus': (((*MOLLUSCS,'주꾸미'), ('손질 주꾸미 400G(봉)',)),),
 'food.seafood.molluscs.small_octopus': (((*MOLLUSCS,'낙지문어'), ('손질 생물 낙지 400G(봉)',)),),
 'food.seafood.shellfish.clam': (
     ((ROOT,'어패류','기타 어패류','기타조개'), ('동죽 조개 (국산) 600G(봉)', '백생합(중국산) 1.5KG')),
     ((ROOT,'어패류','굴/바지락','바지락'), ('바지락살 80G (팩)',)),
 ),
 'food.seafood.processed.squid_shreds': ((SQUID, (
     '부드러운 2.5mm 백진미 오징어채 180Gx2봉', '지금한끼 2mm 오징어실채 80G',
     '자외선살균 백진미 오징어채 300G', '부드러운 2.5mm 백진미 오징어채 150G',
     '지금한끼 백진미오징어채 100G', '홍진미 오징어채 200G', '홍진미 오징어채 150G',
     '부드러운 2.5mm 백진미 오징어채 200G',
 )),),
 'food.seafood.processed.dried_pollock': ((POLL, ('황태채 250G(봉)', '황태채 200G(봉)')),),
 'food.seafood.processed.dried_shrimp': ((DRIED_SHRIMP, ('강화도 보리새우 200G', '고소한 꽃새우(두절) 100G', '강화도 분홍새우 100G(봉)')),),
 'food.seafood.processed.stock_pack': (((ROOT,'건오징어/건어물/다시팩','기타다시팩','다시육수팩'), ('멸치 해산물 다시팩 300G(15Gx20입)',)),),
 'food.seafood.processed.dried_dipori': (((ROOT,'건오징어/건어물/다시팩','기타다시팩','다시육수팩'), ('남해안 국물용 디포리 200G(봉)',)),),
 'food.seafood.seaweed.laver': (
     ((*LAVER,'김밥김'), ('구운 김밥김 10매 20G', '대천김 구이 김밥용 김 22G*3봉')),
     ((*LAVER,'도시락김'), ('올리브유 바삭 파래김 4G*12봉', '대천 참기름 곱창돌김 ECO (4G*20봉)')),
     ((*LAVER,'김부각'), ('고소한 참기름 돌 김자반 50G', '올리브유 돌자반 50G')),
 ),
 'food.meals.seafood.stir_fried': ((FROZEN, ('용두동 주꾸미볶음 500G(250G*2)(봉)', '용두동 낙지볶음 508G(봉)')),),
 'food.meals.seafood.steamed': ((FROZEN, ('국내산 순살아귀찜 400G(봉)',)),),
}
ENTRIES = {(tuple(path), title): leaf for leaf, groups in GROUPS.items() for path, titles in groups for title in titles}


def reviewed_homeplus_seafood_leaf(evidence):
    if evidence['mart'] != 'homeplus':
        return None
    return ENTRIES.get((tuple(evidence['source_path_parts']), evidence['source_title']))
