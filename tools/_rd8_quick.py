import sqlite3
c = sqlite3.connect(r'E:\pdf\capston01\packages\db-admin\backend\walletguardian.db')
print('=== baseline_prices.source distribution ===')
for r in c.execute('SELECT source, COUNT(*) cnt FROM baseline_prices GROUP BY source ORDER BY cnt DESC'):
    print(' ', r)
print()
print('=== baseline rows per product (dist) ===')
for r in c.execute('SELECT n, COUNT(*) cnt FROM (SELECT product_id, COUNT(*) n FROM baseline_prices GROUP BY product_id) GROUP BY n'):
    print(' ', r)
print()
print('=== "CJ 햇반" products + baseline ===')
sql = "SELECT p.id, p.name, p.unit, bp.source, bp.price FROM products p JOIN baseline_prices bp ON bp.product_id=p.id WHERE p.name='CJ 햇반' LIMIT 8"
for r in c.execute(sql):
    print(' ', r)
print()
print('=== matching_entries match_key sample ===')
for r in c.execute('SELECT match_key, category_id, source, confidence FROM matching_entries LIMIT 5'):
    print(' ', r)
