import re, sys
t = open('tests/fixtures/homeplus_probe_search.html', encoding='utf-8', errors='ignore').read()
patterns = [
    r'href="(/[a-z][^"]+H\d{6,}[^"]*)"',
    r'href="([^"]*item[^"]*)"',
    r'/(?:item|goods)/(H\d+[A-Z0-9]*)',
    r'(H\d{6,}N\d+O\d+)',
]
for pat in patterns:
    matches = re.findall(pat, t)[:6]
    print(pat, '->', matches)
print('docId pattern count:', len(re.findall(r'H\d{6,}N\d+O\d+', t)))
