from bs4 import BeautifulSoup
import pathlib, re

html = pathlib.Path(r'promotions_scrolled_full_234444.html').read_text(encoding='utf-8', errors='ignore')
soup = BeautifulSoup(html, 'html.parser')
cards = soup.select('.product-card-container')
print(f'Total cards: {len(cards)}')
if cards:
    c = cards[0]
    print('--- data-test attrs in card 0 ---')
    for el in c.find_all(attrs={'data-test': True}):
        dt = el['data-test']
        txt = el.get_text(strip=True)[:60]
        print(f'  tag={el.name} data-test={dt!r} text={txt!r}')
    print('--- data-synthetics ---')
    for el in c.find_all(attrs={'data-synthetics': True}):
        print(f'  tag={el.name} data-synthetics={el["data-synthetics"]!r}')
    print('--- img tags ---')
    for img in c.find_all('img'):
        src = (img.get('src') or '')[:80]
        alt = img.get('alt', '')
        dt = img.get('data-test', '')
        print(f'  img src={src!r} alt={alt!r} data-test={dt!r}')

# Check how many cards have a fop-price element
with_price = sum(1 for c in cards if c.select_one('[data-test="fop-price"]'))
with_orig = sum(1 for c in cards if c.select_one('[data-test="fop-original-price"]'))
with_synthetics = sum(1 for c in cards if c.find(attrs={'data-synthetics': re.compile(r'product-id')}))
with_img_alt = sum(1 for c in cards if c.select_one('img[data-test="lazy-load-image"]'))
print(f'\nCards with fop-price: {with_price}/{len(cards)}')
print(f'Cards with fop-original-price: {with_orig}/{len(cards)}')
print(f'Cards with product-id synthetics: {with_synthetics}/{len(cards)}')
print(f'Cards with lazy-load-image: {with_img_alt}/{len(cards)}')

# Show card 5's full html
if len(cards) > 5:
    print('\n--- Card 5 raw HTML (first 2000 chars) ---')
    print(str(cards[5])[:2000])
