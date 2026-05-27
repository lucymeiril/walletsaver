# Round R G4-prompt Report

## 산출물
- `E:\pdf\capston01\packages\ai-admin\backend\prompts\external_classify_instructions_v1.md`
  - 외부 경량 AI용 한국어 공용 지침.
  - 기존 카테고리 우선, 없으면 신규 카테고리 제안 원칙과 출력 3종 형식을 명시.
- `E:\pdf\capston01\devlog\round-R\G4-io-spec.md`
  - export 4종(`unclassified.jsonl`, `category_list.yaml`, `keyword_list.yaml`, `instructions.md`)과 import 3종(`matching_updates.jsonl`, `category_keyword_updates.yaml`, `product_updates.jsonl`) 필드·검증 규칙·예시를 정의.
- `E:\pdf\capston01\packages\db-admin\backend\services\external_ai_export.py`
  - `export_unclassified_bundle(out_dir: Path) -> ExportManifest` 스켈레톤.
  - DB 쿼리는 placeholder이며 빈 `unclassified.jsonl`, 카테고리/키워드 목록, 지침 파일, `manifest.json`을 생성.
- `E:\pdf\capston01\packages\db-admin\backend\services\external_ai_import.py`
  - 3종 import 파일 파싱 및 pydantic 스키마 검증 스켈레톤.
  - DB 쓰기는 `apply_import_bundle()` placeholder로 검증만 수행.
- `E:\pdf\capston01\packages\db-admin\backend\tests\test_external_ai_export.py`
  - 빈 DB placeholder 기준 빈 bundle 생성 검증.
- `E:\pdf\capston01\packages\db-admin\backend\tests\test_external_ai_import.py`
  - 정상 bundle 검증, 스키마 위반 검증.

## 핵심 결정 사항
- `canon_hash`는 Round R G0 공식 `SHA1(brand|normalized_name|pack_qty|pack_unit)`의 결과로 보고, 외부 AI가 재계산하지 않도록 했다.
- 신규 카테고리는 category tree를 직접 수정하지 않고 `category_keyword_updates.yaml` 제안으로만 전달한다.
- 키워드는 한국어 중심이며, `쌀`처럼 1글자 필수 키워드가 존재하므로 검증기는 1~20자를 허용한다.
- export skeleton은 실제 DB 연결 없이 파일 구조와 manifest 계약만 고정했다.
- import skeleton은 schema validation까지만 담당하고 실제 DB 반영은 후속 단계로 분리했다.

## 검증
```powershell
cd packages\db-admin\backend; py -3 -m pytest tests\test_external_ai_export.py tests\test_external_ai_import.py -q
```

결과: `3 passed in 0.28s`

## 다음 단계
- `g4-import`: 실제 DB-admin canonical 모델과 연결해 미분류 상품 조회, 기존 카테고리/키워드 export, import 적용 트랜잭션을 구현한다.
- `g4-e2e`: 크롤러 export → 외부 AI 산출물 → DB-admin import → 매칭/카테고리/키워드 업데이트 라이브 사이클을 검증한다.
