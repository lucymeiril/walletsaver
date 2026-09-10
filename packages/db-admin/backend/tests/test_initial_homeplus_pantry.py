import pytest
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy

@pytest.mark.parametrize("path,title,leaf", [
    (["식용유/참기름", "참기름/들기름", "들기름"], "CJ 100%통들깨들기름 160ML", "oils.perilla"),
    (["식용유/참기름", "포도씨/카놀라유/식용유/기타유", "식용유"], "CJ 백설 콩기름(식용유) 1.8L", "oils.soybean"),
    (["식용유/참기름", "포도씨/카놀라유/식용유/기타유", "포도씨/카놀라유/기타"], "simplus 아보카도 오일 1L", "oils.avocado"),
    (["소스", "굴소스/두반장/기타", "굴소스/두반장"], "CJ 백설 프리미엄 굴소스 350G", "sauces.oyster"),
    (["소스", "돈까스/스테이크소스"], "오뚜기 경양식 돈까스 소스 455G", "sauces.tonkatsu"),
    (["소스", "돈까스/스테이크소스"], "오뚜기 타타르소스 245G", "sauces.tartar"),
    (["소스", "불고기/갈비양념장"], "CJ 백설 소갈비양념 500G", "sauces.meat"),
    (["소스", "샐러드드레싱/발사믹"], "청정원 저당 참깨 드레싱 310G", "sauces.dressing"),
    (["소스", "칠리/월남쌈/쌀국수소스"], "친수 피쉬소스 300G", "sauces.fish"),
    (["고추장/된장/쌈장/간장", "고추장/초고추장"], "CJ 해찬들 새콤 달콤 초고추장 300G", "sauces.cho_gochujang"),
    (["고추장/된장/쌈장/간장", "고추장/초고추장"], "대상 청정원 순창 찰고추장 500G", "pastes.gochujang"),
    (["고추장/된장/쌈장/간장", "고추장/초고추장"], "CJ 100%우리쌀 태양초고추장 500G", "pastes.gochujang"),
])
def test_pantry_forms(path,title,leaf):
    leaf = "food.seasonings." + leaf
    assert classify_record({"source_name":"homeplus", "source_category_path":["장류/양념/제빵", *path], "source_title":title})["unified_category_id"] == leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})

@pytest.mark.parametrize("mart,path", [("emart", ["장류/양념/제빵", "소스", "돈까스/스테이크소스"]), ("homeplus", ["장류/양념/제빵"])])
def test_unreviewed_context_not_inferred(mart,path):
    assert classify_record({"source_name":mart,"source_category_path":path,"source_title":"오뚜기 타타르소스 245G"})["unified_category_id"] is None

def test_opaque_oil_not_inferred():
    assert classify_record({"source_name":"homeplus", "source_category_path":["장류/양념/제빵","식용유/참기름","포도씨/카놀라유/식용유/기타유","포도씨/카놀라유/기타"], "source_title":"만토바 230도 오일스프레이 200ML"})["unified_category_id"] is None
