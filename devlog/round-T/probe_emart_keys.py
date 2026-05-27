"""emart __NEXT_DATA__ product 객체 키 + 셀러/promo 필드 식별."""
import re, json, time, requests, sys
sess = requests.Session()
sess.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Accept': 'text/html,application/xhtml+xml',
    'Referer': 'https://emart.ssg.com/',
})
sess.get('https://emart.ssg.com/', timeout=15)
time.sleep(3)
r = sess.get('https://emart.ssg.com/search.ssg?target=all&query=%ED%96%89%EC%82%AC&page=1', timeout=20)
m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
data = json.loads(m.group(1))

def collect(node, out, depth=0):
    if depth > 8: return
    if isinstance(node, dict):
        dl = node.get('dataList')
        if isinstance(dl, list) and dl and isinstance(dl[0], dict) and 'itemId' in dl[0] and 'itemName' in dl[0]:
            out.extend(dl)
        for v in node.values():
            collect(v, out, depth+1)
    elif isinstance(node, list):
        for v in node:
            collect(v, out, depth+1)

products = []
collect(data, products)
print('PRODUCTS', len(products))
if products:
    p = products[0]
    print('\n=== ALL KEYS (sample 1) ===')
    for k in sorted(p.keys()):
        v = p[k]
        if isinstance(v, (dict, list)):
            print(f'  {k}: {type(v).__name__} len={len(v) if hasattr(v,"__len__") else "?"} sample={str(v)[:120]}')
        else:
            print(f'  {k}: {v!r:.120}')
    print('\n=== seller / site / promo fields across 5 products ===')
    for i, p in enumerate(products[:5]):
        promo_keys = {k: p[k] for k in p if any(s in k.lower() for s in ['seller','site','vendor','shop','partner','badge','promo','benefit','bogo','event','tag','plus','label','1','dely','dlv','ship'])}
        print(f'#{i}', p.get('itemName','')[:40], '|', json.dumps(promo_keys, ensure_ascii=False)[:400])
    print('\n=== itemName containing 1+1 / 2+1 ===')
    import collections
    promo_names = [p for p in products if re.search(r'\d\+\d', p.get('itemName',''))]
    print(f'  found {len(promo_names)}')
    for p in promo_names[:3]:
        print('  ->', p.get('itemName')[:80], '| keys-with-bogo:',
              {k:p[k] for k in p if 'bogo' in k.lower() or 'promo' in k.lower() or 'benefit' in k.lower() or 'badge' in k.lower()})
