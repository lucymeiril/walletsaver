"""rd8_pack_fillin.py — products의 pack_qty/pack_unit NULL을 이름·matching_entry로 보강.

전략:
1. matching_entries에서 같은 brand+name_core 매칭으로 pack_qty/pack_unit 가져오기
2. 그래도 없으면 name_core 정규식 파싱 (rd8_lottemart_normalize와 동일 로직)
3. 그래도 없으면 (1.0, "ea") 디폴트
4. unit_price_normalized = price / pack_qty (weight: per 100g, volume: per 100ml, count: per ea)
"""
import sqlite3, re
DB = r'E:\pdf\capston01\packages\db-admin\backend\walletguardian.db'

UNIT_MAP = {
    "g":("g","weight"),"kg":("g","weight"),"mg":("g","weight"),
    "ml":("ml","volume"),"l":("ml","volume"),"cc":("ml","volume"),
    "ea":("ea","count"),"개":("ea","count"),"개입":("ea","count"),"입":("ea","count"),
    "포":("ea","count"),"팩":("ea","count"),"장":("ea","count"),"매":("ea","count"),
    "병":("ea","count"),"캔":("ea","count"),"봉":("ea","count"),"롤":("ea","count"),
    "구":("ea","count"),"통":("ea","count"),"마리":("ea","count"),"인":("ea","count"),
}
PAT = re.compile(r"\(([\d.,]+)\s*([A-Za-z가-힣]+)\)|([\d.,]+)\s*(KG|G|MG|ML|L|CC|EA|개|입|포|팩|장|매|병|캔|봉|롤|마리|인)\b", re.I)
PAT_EA = re.compile(r"\((EA|개|마리|통|인|입|개입|팩|봉|병|캔)\)", re.I)

def parse(name):
    if not name: return None,None
    ms = list(PAT.finditer(name))
    if ms:
        m = ms[-1]
        if m.group(1):
            num,u = m.group(1), m.group(2)
        else:
            num,u = m.group(3), m.group(4)
        try: qty = float(num.replace(",",""))
        except: return None,None
        ul = u.lower().strip()
        if ul in UNIT_MAP:
            nu,_ = UNIT_MAP[ul]
            if ul=="kg": qty*=1000
            elif ul=="l": qty*=1000
            elif ul=="mg": qty/=1000
            return qty, nu
        return qty, ul
    m = PAT_EA.search(name)
    if m:
        u = m.group(1).lower()
        return 1.0, UNIT_MAP.get(u,("ea","count"))[0]
    return None, None

c = sqlite3.connect(DB)

# 1단계: matching_entry 룩업
rows = c.execute("""
    SELECT p.id, p.brand, p.name_core, p.name FROM products p
    WHERE p.pack_qty IS NULL OR p.pack_unit IS NULL OR p.pack_unit=''
""").fetchall()
print(f"NULL pack rows: {len(rows)}")

fill_from_me = 0
fill_from_name = 0
fill_default = 0
for pid, brand, nc, name in rows:
    # matching_entry 매칭
    me = c.execute(
        "SELECT pack_qty, pack_unit FROM matching_entries WHERE brand=? AND name_core=? AND pack_qty IS NOT NULL LIMIT 1",
        (brand, nc)
    ).fetchone()
    qty, unit = None, None
    if me and me[0] is not None:
        qty, unit = me[0], me[1]
        fill_from_me += 1
    else:
        qty, unit = parse(name or nc or "")
        if qty is not None:
            fill_from_name += 1
        else:
            qty, unit = 1.0, "ea"
            fill_default += 1
    c.execute("UPDATE products SET pack_qty=?, pack_unit=?, unit=? WHERE id=?", (qty, unit, unit, pid))

c.commit()
print(f"  filled from matching_entry: {fill_from_me}")
print(f"  filled from name parse: {fill_from_name}")
print(f"  default (1,ea): {fill_default}")

# 2단계: unit_price_normalized 재계산
print("\n=== unit_price_normalized 재계산 ===")
# 단가 기준: weight→per 100g, volume→per 100ml, count→per ea
br = c.execute("""
    SELECT bp.id, bp.product_id, bp.price, p.pack_qty, p.pack_unit
    FROM baseline_prices bp
    JOIN products p ON bp.product_id = p.id
    WHERE bp.unit_price_normalized IS NULL OR p.pack_qty IS NOT NULL
""").fetchall()
print(f"baseline 후보: {len(br)}")
upd = 0
for bid, pid, price, pq, pu in br:
    if not pq or pq <= 0 or not price:
        continue
    pu_l = (pu or "").lower()
    if pu_l == "g":
        unit_price = (price / pq) * 100  # per 100g
        basis = "per_100g"
    elif pu_l == "ml":
        unit_price = (price / pq) * 100
        basis = "per_100ml"
    else:
        unit_price = price / pq
        basis = f"per_{pu_l or 'ea'}"
    c.execute("UPDATE baseline_prices SET unit_price_normalized=?, unit_price_basis=? WHERE id=?",
              (round(unit_price,2), basis, bid))
    upd += 1
c.commit()
print(f"  unit_price 갱신: {upd}")

# 3단계: 비-leaf products를 가장 가까운 leaf로 — 간단히 같은 부모의 첫 leaf 자식으로
print("\n=== 비-leaf products 처리 ===")
cats = {r[0]: r[1] for r in c.execute("SELECT id, parent_id FROM categories")}
children = {}
for cid, pid in cats.items():
    if pid: children.setdefault(pid, []).append(cid)
leaf_set = {cid for cid in cats if cid not in children}

def first_leaf_under(cid):
    stack = [cid]
    while stack:
        x = stack.pop()
        if x in leaf_set:
            return x
        stack.extend(children.get(x, []))
    return None

nonleaf = c.execute("""
    SELECT id, category_id FROM products WHERE category_id NOT IN (
        SELECT id FROM categories c WHERE NOT EXISTS (SELECT 1 FROM categories c2 WHERE c2.parent_id=c.id)
    )
""").fetchall()
print(f"  비-leaf rows: {len(nonleaf)}")
remap = 0
for pid, cid in nonleaf:
    leaf = first_leaf_under(cid)
    if leaf:
        c.execute("UPDATE products SET category_id=? WHERE id=?", (leaf, pid))
        remap += 1
c.commit()
print(f"  remap to leaf: {remap}")

# 최종 검증
print("\n=== FINAL ===")
print(f"  pack_qty NULL: {c.execute('SELECT COUNT(*) FROM products WHERE pack_qty IS NULL').fetchone()[0]}")
print(f"  pack_unit NULL/공백: {c.execute(chr(34)+'SELECT COUNT(*) FROM products WHERE pack_unit IS NULL OR pack_unit='+chr(39)+chr(39)+chr(34)).fetchone()[0]}")
print(f"  unit_price NULL: {c.execute('SELECT COUNT(*) FROM baseline_prices WHERE unit_price_normalized IS NULL').fetchone()[0]}")
nl = c.execute("""SELECT COUNT(*) FROM products WHERE category_id NOT IN (
    SELECT id FROM categories c WHERE NOT EXISTS (SELECT 1 FROM categories c2 WHERE c2.parent_id=c.id))""").fetchone()[0]
print(f"  비-leaf products: {nl}")
