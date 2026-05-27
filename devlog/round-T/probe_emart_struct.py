import re, json, time, requests
sess = requests.Session()
sess.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Referer': 'https://emart.ssg.com/',
})
sess.get('https://emart.ssg.com/', timeout=15); time.sleep(3)
r = sess.get('https://emart.ssg.com/search.ssg?target=all&query=%ED%96%89%EC%82%AC&page=1', timeout=20)
print('STATUS', r.status_code, 'LEN', len(r.text))
m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
if not m:
    print('NO __NEXT_DATA__')
    # try other patterns
    for pat in [r'window\.__INITIAL_STATE__\s*=\s*({.*?});</script>',
                r'__APP_DATA__\s*=\s*({.*?})\s*</script>',
                r'<script id="__APOLLO_STATE__"[^>]*>(.*?)</script>']:
        mm = re.search(pat, r.text, re.S)
        if mm: print('FOUND', pat, 'len', len(mm.group(1)))
    # find itemView count
    print('itemView.ssg count', len(re.findall(r'itemView\.ssg', r.text)))
    print('item_unit count', len(re.findall(r'class="cunit_t', r.text)))
    print('sample first 2000 chars:')
    print(r.text[:2000])
else:
    data = json.loads(m.group(1))
    print('TOP KEYS', list(data.keys()))
    print('props.pageProps keys', list(data.get('props',{}).get('pageProps',{}).keys())[:30])
    # dump structure paths up to depth 3
    INTEREST = {'itemId','itemName','prdNm','prdId','displayName','salePrice','price','finalPrice','itemList','products','dataList','goodsList','prodList','items','searchResult','prodInfo'}
    def walk(n, path, depth=0):
        if depth > 10: return
        if isinstance(n, dict):
            for k,v in n.items():
                p2 = f'{path}.{k}'
                if k in INTEREST and not isinstance(v,(dict,list)):
                    print(f'{p2} = {str(v)[:80]}')
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    keys0 = list(v[0].keys())[:12]
                    if any(x in v[0] for x in ('itemId','itemName','prdNm','prdId','displayName')):
                        print(f'>>> PRODUCT-LIKE {p2}[{len(v)}] keys={keys0}')
                    elif k in INTEREST:
                        print(f'    {p2}[{len(v)}] keys={keys0}')
                walk(v, p2, depth+1)
        elif isinstance(n, list):
            for i,v in enumerate(n[:3]):
                walk(v, f'{path}[{i}]', depth+1)
    walk(data, 'root')
