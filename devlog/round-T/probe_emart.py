"""sandbox 라이브 emart 검증 — Round T."""
import re, time, requests, json, sys

sess = requests.Session()
sess.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
    'Referer': 'https://emart.ssg.com/',
})

# warm up homepage
r0 = sess.get('https://emart.ssg.com/', timeout=15)
print('HOME', r0.status_code, len(r0.text))
time.sleep(2)

r = sess.get('https://emart.ssg.com/search.ssg?target=all&query=%ED%96%89%EC%82%AC&page=1', timeout=20)
print('SEARCH STATUS', r.status_code, 'LEN', len(r.text), 'URL', r.url)
for pat in ['__NEXT_DATA__', 'itemView.ssg', 'itemId', 'cdtl_ico_item', 'mnemitem', 'dispCtgId', 'discountRate']:
    print(f'  [{pat}]', len(re.findall(pat, r.text)))

m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
if m:
    nd = m.group(1)
    print('NEXT_DATA LEN', len(nd))
    try:
        data = json.loads(nd)
        # find items
        def walk(o, depth=0):
            if depth > 6: return
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ('items', 'itemList', 'productList', 'goods', 'goodsList') and isinstance(v, list) and v:
                        print(f'  FOUND key={k} depth={depth} len={len(v)}')
                        if v and isinstance(v[0], dict):
                            print(f'    sample keys: {list(v[0].keys())[:20]}')
                    walk(v, depth + 1)
            elif isinstance(o, list):
                for x in o[:3]:
                    walk(x, depth + 1)
        walk(data)
    except Exception as e:
        print('JSON parse FAIL', e)
else:
    print('NO __NEXT_DATA__')
    # try category instead
    print('--- TRY DISP CATEGORY ---')
    r2 = sess.get('https://emart.ssg.com/disp/category.ssg?dispCtgId=6000095331', timeout=20)
    print('CAT STATUS', r2.status_code, 'LEN', len(r2.text))
    # check for ssg search API
    print('--- TRY API ssg.com ---')
    for url in [
        'https://emart.ssg.com/search.ssg?query=%EC%A0%84%EB%8B%A8',
        'https://emart.ssg.com/disp/category.ssg?ctgId=6000095331',
    ]:
        rr = sess.get(url, timeout=15)
        print(f'  {url} -> {rr.status_code} len={len(rr.text)} body_has_NEXT={"__NEXT_DATA__" in rr.text} title_match={bool(re.search(r"<title>([^<]+)</title>", rr.text))}')
        time.sleep(2)
