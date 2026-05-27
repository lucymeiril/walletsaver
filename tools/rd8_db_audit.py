import sqlite3, json
c = sqlite3.connect(r'E:\pdf\capston01\packages\db-admin\backend\walletguardian.db')

print("=== 카운트 ===")
for t in ('products', 'baseline_prices', 'matching_entries', 'categories', 'keywords'):
    n = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'  {t}: {n}')

print("\n=== Products: NULL 검사 ===")
for col in ('brand', 'name_core', 'pack_qty', 'pack_unit', 'category_id', 'source_marts'):
    n = c.execute(f"SELECT COUNT(*) FROM products WHERE {col} IS NULL OR {col}=''").fetchone()[0]
    print(f'  {col} NULL/공백: {n}')

print("\n=== Products: 중복 (brand|name_core|pack_qty|pack_unit) ===")
dup = c.execute("""
    SELECT brand, name_core, pack_qty, pack_unit, COUNT(*) c
    FROM products GROUP BY brand,name_core,pack_qty,pack_unit
    HAVING c > 1 ORDER BY c DESC LIMIT 10
""").fetchall()
print(f'  중복 그룹 수: {len(dup)}')
for r in dup[:5]: print(f'    {r}')

print("\n=== Baseline: mart_code 분포 ===")
for r in c.execute("SELECT mart_code, COUNT(*) FROM baseline_prices GROUP BY mart_code"):
    print(f'  {r}')

print("\n=== Baseline NULL ===")
for col in ('mart_code', 'unit_price_normalized'):
    n = c.execute(f"SELECT COUNT(*) FROM baseline_prices WHERE {col} IS NULL OR {col}=''").fetchone()[0]
    print(f'  {col} NULL: {n}')

print("\n=== Category: leaf check ===")
# 검사: products.category_id가 categories 테이블에 있고, 그 카테고리에 자식이 없는지
cats = {r[0]: r[1] for r in c.execute("SELECT id, parent_id FROM categories")}
children = {}
for cid, pid in cats.items():
    if pid:
        children.setdefault(pid, []).append(cid)
leaf_set = {cid for cid in cats if cid not in children}
non_leaf_products = c.execute("SELECT category_id, COUNT(*) FROM products GROUP BY category_id").fetchall()
bad = [(cid, n) for cid, n in non_leaf_products if cid and cid not in leaf_set]
print(f'  비-leaf products: {sum(n for _,n in bad)}건 ({len(bad)} 카테고리)')
for r in bad[:5]: print(f'    {r}')

print("\n=== Category 분포 Top 15 ===")
for r in c.execute("SELECT category_id, COUNT(*) FROM products GROUP BY category_id ORDER BY COUNT(*) DESC LIMIT 15"):
    print(f'  {r}')

print("\n=== source_marts 채움 ===")
mart_counts = {}
for (sm,) in c.execute("SELECT source_marts FROM products WHERE source_marts IS NOT NULL"):
    try:
        marts = json.loads(sm) if sm else []
        for m in marts:
            mart_counts[m] = mart_counts.get(m, 0) + 1
    except:
        pass
print(f'  source_marts 분포: {mart_counts}')
empty_sm = c.execute("SELECT COUNT(*) FROM products WHERE source_marts IS NULL OR source_marts='[]' OR source_marts='null'").fetchone()[0]
print(f'  source_marts 비어있음: {empty_sm}')

print("\n=== 마트별 baseline 평균 ===")
for r in c.execute("""
    SELECT mart_code, COUNT(*) total, COUNT(DISTINCT product_id) distinct_products,
           ROUND(AVG(unit_price_normalized), 2) avg_unit_price
    FROM baseline_prices GROUP BY mart_code
"""):
    print(f'  {r}')
