import re, time, requests
s = requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36','Accept-Language':'ko-KR,ko;q=0.9','Referer':'https://emart.ssg.com/'})
s.get('https://emart.ssg.com/', timeout=15); time.sleep(3)
for shpp in ('', 'ssgem', 'smon'):
    url = 'https://emart.ssg.com/search.ssg?target=all&query=%EC%B1%84%EC%86%8C&page=1'
    if shpp:
        url += '&shpp=' + shpp
    r = s.get(url, timeout=20)
    iv = len(re.findall(r'itemView\.ssg', r.text))
    nd = '__NEXT_DATA__' in r.text
    name = shpp if shpp else 'none'
    print('shpp=%-6s status=%d len=%d itemView=%d next_data=%s' % (name, r.status_code, len(r.text), iv, nd))
    time.sleep(3)
