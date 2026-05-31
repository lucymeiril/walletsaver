# 외부 분류 공용 지침 (external classification instructions) v1

이 문서는 미분류 상품을 외부 경량 LLM으로 분류할 때 동봉되는 공용 지침입니다.
(ai-admin 라이브 파이프라인 폐기 후, 외부 분류 워크플로우의 지침 원본을 db-admin 으로 이관)

## 입력
- `unclassified.jsonl` — 분류 대상 상품 목록(JSONL)
- `category_list.yaml` — 통합 카테고리 목록(leaf 노드만 분류 대상)
- `keyword_list.yaml` — 기존 키워드/별칭 목록

## 작업
각 상품을 `category_list.yaml`의 **leaf** 카테고리 중 하나로 분류하고, 근거 키워드를 제시한다.

## 출력 규칙
- 반드시 leaf 카테고리 id 만 사용한다(루트/중간 노드 금지).
- 확신이 없으면 분류하지 말고 `unmatched` 로 남긴다(억지 매칭 금지).
- 브랜드/용량/단위는 상품명에서 추론하되, 불확실하면 비워 둔다.

## 반환 형식
`import` 단계가 받는 JSONL 스키마(`external-ai-classify-v1`)를 따른다.
