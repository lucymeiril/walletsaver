#!/usr/bin/env python3
"""
일회성 코스트코 중복 진단 스크립트
- 최근 캡처 데이터에서 중복 이름 검출
- 정규화는 진단 목적으로만 사용 (크롤러 코드에 반영하지 않음)
"""

import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

def normalize_product_name(name: str) -> str:
    """
    상품명 정규화: 특수기호 제거
    - 괄호 제거 (숫자 유닛 표기 포함): (400G X 4EA) → 없음
    - 별표 제거
    - 한자 단위는 보존 (미국산 등)
    - 공백 정규화
    """
    if not name:
        return ""
    
    # 괄호와 내용 제거
    normalized = re.sub(r'\([^)]*\)', '', name)
    
    # 별표 제거
    normalized = re.sub(r'\*+', '', normalized)
    
    # 연속 공백 정규화
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # 양쪽 공백 제거
    normalized = normalized.strip()
    
    return normalized


def load_all_costco_captures(base_path: str) -> List[Dict]:
    """세 개 캡처 파일 모두 로드"""
    all_records = []
    capture_dir = Path(base_path) / ".walletsavior-live-validation" / "ai-live-run" / "costco-capture"
    
    if not capture_dir.exists():
        raise FileNotFoundError(f"Capture directory not found: {capture_dir}")
    
    json_files = sorted(capture_dir.glob("costco-cocodalin-capture-*.json"))
    print(f"[찾음] {len(json_files)}개 파일 발견:")
    
    for json_file in json_files:
        print(f"  - {json_file.name}")
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            raw_records = data.get('raw_records', [])
            all_records.extend(raw_records)
            print(f"    └─ {len(raw_records)}개 행")
    
    return all_records


def analyze_duplicates(records: List[Dict]) -> Dict:
    """중복 분석"""
    print(f"\n[분석] 총 {len(records)}개 행 처리 중...\n")
    
    # 1. 정규화 전 고유 이름
    raw_names = set(r.get('raw_title', '') for r in records)
    print(f"✓ 정규화 전 고유 이름: {len(raw_names)}개")
    
    # 2. 정규화 후 매핑
    normalized_to_raw = defaultdict(list)
    
    for record in records:
        raw_title = record.get('raw_title', '')
        normalized = normalize_product_name(raw_title)
        
        if normalized:  # 빈 문자열 제외
            normalized_to_raw[normalized].append({
                'raw_title': raw_title,
                'category': record.get('raw_payload', {}).get('category', 'N/A'),
                'price': record.get('raw_price'),
                'source_key': record.get('source_record_key')
            })
    
    print(f"✓ 정규화 후 고유 이름: {len(normalized_to_raw)}개")
    
    # 3. 중복 통계
    duplicates = {norm: items for norm, items in normalized_to_raw.items() if len(items) > 1}
    total_dup_rows = sum(len(items) for items in duplicates.values())
    
    print(f"✓ 중복 그룹: {len(duplicates)}개")
    print(f"✓ 중복 그룹에 포함된 총 행: {total_dup_rows}개")
    
    # 4. Top 10 중복
    top_dups = sorted(
        duplicates.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )[:10]
    
    # 5. 잠재 누락 후보 (이름 길이 편차 또는 카테고리 spread)
    suspicious = []
    for norm, items in normalized_to_raw.items():
        categories = set(item['category'] for item in items)
        prices = [item['price'] for item in items if item['price']]
        
        # 같은 이름인데 카테고리가 다르면 의심
        if len(categories) > 1:
            suspicious.append({
                'normalized': norm,
                'count': len(items),
                'categories': list(categories),
                'raw_titles': list(set(item['raw_title'] for item in items))
            })
    
    suspicious = sorted(suspicious, key=lambda x: x['count'], reverse=True)[:10]
    
    return {
        'total_raw_rows': len(records),
        'unique_raw_names': len(raw_names),
        'unique_normalized_names': len(normalized_to_raw),
        'duplicate_groups': len(duplicates),
        'duplicate_rows_total': total_dup_rows,
        'top_duplicates': top_dups,
        'suspicious_candidates': suspicious,
        'all_normalized': normalized_to_raw
    }


def print_report(analysis: Dict) -> None:
    """결과 리포트 출력"""
    print("\n" + "=" * 70)
    print("코스트코 중복 진단 리포트")
    print("=" * 70)
    
    print(f"\n[요약]")
    print(f"  • 원본 행 수: {analysis['total_raw_rows']}")
    print(f"  • 정규화 전 고유 이름: {analysis['unique_raw_names']}")
    print(f"  • 정규화 후 고유 이름: {analysis['unique_normalized_names']}")
    print(f"  • 중복 그룹 수: {analysis['duplicate_groups']}")
    print(f"  • 중복에 포함된 행: {analysis['duplicate_rows_total']}")
    
    reduction = analysis['unique_raw_names'] - analysis['unique_normalized_names']
    print(f"\n[정규화 효과]")
    print(f"  • 정규화로 제거된 고유 이름 수: {reduction}")
    print(f"  • 감소율: {reduction / analysis['unique_raw_names'] * 100:.2f}%")
    
    print(f"\n[Top 10 중복 (같은 정규화 이름에 매핑)]")
    for i, (normalized, items) in enumerate(analysis['top_duplicates'], 1):
        print(f"\n{i}. '{normalized}'")
        print(f"   개수: {len(items)}")
        print(f"   가격 범위: {min(i['price'] for i in items if i['price'])} ~ {max(i['price'] for i in items if i['price'])}")
        categories = set(item['category'] for item in items)
        print(f"   카테고리: {', '.join(categories) if categories else 'N/A'}")
        print(f"   원본 제목 목록:")
        for item in items[:3]:  # 처음 3개만 표시
            print(f"     - {item['raw_title']}")
        if len(items) > 3:
            print(f"     ... 외 {len(items) - 3}개")
    
    print(f"\n[잠재 누락 후보 (같은 이름, 다른 카테고리)]")
    if analysis['suspicious_candidates']:
        for i, cand in enumerate(analysis['suspicious_candidates'], 1):
            print(f"\n{i}. '{cand['normalized']}'")
            print(f"   개수: {cand['count']}")
            print(f"   카테고리 수: {len(cand['categories'])}")
            print(f"   카테고리: {', '.join(cand['categories'])}")
    else:
        print("  (없음)")
    
    print("\n" + "=" * 70)


def save_markdown_report(analysis: Dict, output_path: str) -> None:
    """마크다운 리포트 저장"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    lines = []
    lines.append("# 코스트코 중복 데이터 진단 리포트\n")
    
    lines.append("## 1. 요약\n")
    lines.append(f"- **원본 행 수**: {analysis['total_raw_rows']}")
    lines.append(f"- **정규화 전 고유 이름**: {analysis['unique_raw_names']}")
    lines.append(f"- **정규화 후 고유 이름**: {analysis['unique_normalized_names']}")
    lines.append(f"- **중복 그룹 수**: {analysis['duplicate_groups']}")
    lines.append(f"- **중복에 포함된 행**: {analysis['duplicate_rows_total']}\n")
    
    reduction = analysis['unique_raw_names'] - analysis['unique_normalized_names']
    lines.append("## 2. 정규화 효과\n")
    lines.append(f"정규화(괄호/별표 제거) 후 제거된 고유 이름: **{reduction}개** ({reduction / analysis['unique_raw_names'] * 100:.2f}%)\n")
    
    lines.append("## 3. Top 10 중복\n")
    lines.append("| # | 정규화된 이름 | 개수 | 가격 범위 | 카테고리 |")
    lines.append("|---|---|---|---|---|")
    
    for i, (normalized, items) in enumerate(analysis['top_duplicates'], 1):
        prices = [item['price'] for item in items if item['price']]
        price_range = f"{min(prices)}~{max(prices)}" if prices else "N/A"
        categories = ', '.join(set(item['category'] for item in items))
        escaped_name = normalized.replace('|', '\\|')
        lines.append(f"| {i} | {escaped_name} | {len(items)} | {price_range} | {categories} |")
    lines.append("")
    
    lines.append("## 4. 잠재 누락 후보\n")
    lines.append("같은 정규화 이름에 매핑되었지만 **다른 카테고리**를 가진 상품:\n")
    
    if analysis['suspicious_candidates']:
        for i, cand in enumerate(analysis['suspicious_candidates'], 1):
            lines.append(f"### {i}. {cand['normalized']}")
            lines.append(f"- 개수: {cand['count']}")
            lines.append(f"- 카테고리: {', '.join(cand['categories'])}")
            lines.append(f"- 원본 제목:")
            for title in cand['raw_titles'][:5]:
                lines.append(f"  - {title}")
            if len(cand['raw_titles']) > 5:
                lines.append(f"  - ... 외 {len(cand['raw_titles']) - 5}개")
            lines.append("")
    else:
        lines.append("(없음)\n")
    
    lines.append("## 5. 판정 및 결론\n")
    
    # 판정 로직
    if reduction > 10:
        lines.append("### 📋 **실제 중복 발견**\n")
        lines.append(f"정규화로 {reduction}개의 이름 변형이 통합되었습니다. 이는 다음을 의미합니다:")
        lines.append("- 상품명에 포함된 개수, 크기, 단위 표기가 다양함")
        lines.append("- 예: `DOLE 파인애플`과 `DOLE 파인애플 (400G X 4EA)` → 같은 상품")
        lines.append("- **다음 액션**: 정규화 규칙을 크롤러에 적용하여 원본 데이터를 표준화할 것을 검토")
    else:
        lines.append("### 📋 **다른 SKU이거나 미미한 중복**\n")
        lines.append(f"정규화로 제거된 이름 변형이 {reduction}개로 매우 적습니다.")
        lines.append("- 대부분의 상품이 고유한 이름을 가지고 있음")
        lines.append("- 현재 데이터는 충분히 정규화되어 있음")
    
    lines.append(f"\n**총 처리 대상**: {analysis['total_raw_rows']}행\n")
    
    report_text = "\n".join(lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    
    print(f"\n✅ 리포트 저장: {output_path}")


if __name__ == "__main__":
    import sys
    import os
    
    # 실행 디렉토리
    base_path = os.getcwd()
    
    try:
        # 1. 데이터 로드
        print("[단계 1] 코스트코 캡처 데이터 로드")
        records = load_all_costco_captures(base_path)
        
        # 2. 분석
        print("\n[단계 2] 중복 분석")
        analysis = analyze_duplicates(records)
        
        # 3. 리포트 출력
        print("\n[단계 3] 리포트 생성")
        print_report(analysis)
        
        # 4. 마크다운 저장
        report_path = os.path.expanduser(
            "~/.copilot/session-state/costco_dedup_report.md"
        )
        save_markdown_report(analysis, report_path)
        
        # 5. 요약 출력
        print(f"\n[완료]")
        print(f"실제 중복 (정규화로 제거된 고유 이름): {analysis['unique_raw_names'] - analysis['unique_normalized_names']}개")
        print(f"결론: {'실제 중복 있음' if (analysis['unique_raw_names'] - analysis['unique_normalized_names']) > 10 else '미미한 중복'}")
        
    except Exception as e:
        print(f"\n❌ 오류: {e}", file=sys.stderr)
        sys.exit(1)
