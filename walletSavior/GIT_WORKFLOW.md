# Git 워크플로우

## 브랜치 전략

### 영구 브랜치
- `main` — 안정 버전만. 프로덕션 배포 대상
- `develop` — 통합 브랜치. 기능 브랜치가 여기로 병합

### 임시 브랜치
- `feature/{module-name}` — 모듈별 기능 개발
  - 예: `feature/storage-module`, `feature/crawler-emart`, `feature/fe-hotdeals-page`
- `hotfix/{issue}` — 긴급 수정 (main에서 분기 → main + develop에 병합)
- `release/{version}` — 릴리스 준비 (develop에서 분기 → main에 병합)

## 병합 규칙

### ⚠️ 병합 최소화 원칙
- 브랜치 분기를 유지하고, 불필요한 병합 지양
- 병합 전 반드시 전체 테스트 통과 확인
- 모듈 완성 시에만 develop으로 병합
- main으로의 병합은 릴리스 시에만

### 병합 전 체크리스트
1. [ ] 모든 단위 테스트 통과
2. [ ] 통합 테스트 통과
3. [ ] 회귀 테스트 통과 (기존 기능 영향 없음)
4. [ ] 코드 리뷰 완료
5. [ ] 문서 업데이트 완료
6. [ ] ERROR_LOG.md에 해결된 이슈 기록

## 커밋 규칙

### 커밋 메시지 포맷
```
<type>(<scope>): <description>

[optional body]

[optional footer]

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

### Type
- `feat`: 새 기능
- `fix`: 버그 수정
- `refactor`: 리팩토링
- `test`: 테스트 추가/수정
- `docs`: 문서
- `chore`: 빌드/설정
- `style`: 포맷팅

### Scope
- `core`, `engine`, `crawler`, `storage`, `api`, `auth`
- `fe`, `admin`, `infra`, `ci`

## AI 에이전트 Git 규칙
- 각 모듈 완성 시 feature 브랜치에서 작업
- 테스트 통과 후 develop으로 PR
- ERROR_LOG.md는 develop에 직접 커밋 가능
- devlog/는 develop에 직접 커밋 가능
