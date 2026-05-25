#!/usr/bin/env python3
"""3개 코스트코 캡처 파일 비교"""

import json
from collections import Counter

files = [
    '.walletsavior-live-validation/ai-live-run/costco-capture/costco-cocodalin-capture-20260518-002010.json',
    '.walletsavior-live-validation/ai-live-run/costco-capture/costco-cocodalin-capture-20260518-002050.json',
    '.walletsavior-live-validation/ai-live-run/costco-capture/costco-cocodalin-capture-20260518-002244.json'
]

all_titles = []
file_titles = []

for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        data = json.load(file)
        titles = [r.get('raw_title', '') for r in data.get('raw_records', [])]
        file_titles.append(set(titles))
        all_titles.extend(titles)
        fname = f.split('/')[-1]
        print(f'{fname}: {len(titles)}개 항목')

print(f'\n총 항목: {len(all_titles)}개')
print(f'전체 고유 제목: {len(set(all_titles))}개')

# 각 제목의 출현 횟수
title_counts = Counter(all_titles)
most_common = title_counts.most_common(5)
print(f'\n가장 많이 반복된 제목 Top 5:')
for title, count in most_common:
    short_title = (title[:50] + '...') if len(title) > 50 else title
    print(f'  {count}회: {short_title}')

# 파일 간 교집합 확인
intersection = file_titles[0] & file_titles[1] & file_titles[2]
print(f'\n3개 파일 모두에 공통으로 있는 제목: {len(intersection)}개')

# 파일별 고유 제목
for i, titles in enumerate(file_titles):
    print(f'파일 {i+1} 고유 제목: {len(titles)}개')

# 파일 간 차이 확인
diff_01 = file_titles[0] - file_titles[1]
diff_12 = file_titles[1] - file_titles[2]
diff_20 = file_titles[2] - file_titles[0]

print(f'\n파일 1에만 있는 제목: {len(diff_01)}개')
print(f'파일 2에만 있는 제목: {len(diff_12)}개')
print(f'파일 3에만 있는 제목: {len(diff_20)}개')

if diff_01:
    print('\n파일 1에만 있는 제목:')
    for title in list(diff_01)[:3]:
        print(f'  - {title}')

if diff_12:
    print('\n파일 2에만 있는 제목:')
    for title in list(diff_12)[:3]:
        print(f'  - {title}')

if diff_20:
    print('\n파일 3에만 있는 제목:')
    for title in list(diff_20)[:3]:
        print(f'  - {title}')
