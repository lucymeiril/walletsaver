"""운영자 워크밴치 정책 — 단일 진실 소스.

이 모듈이 존재하는 이유 (다음 AI를 위한 의도 보존):
-----------------------------------------------------------------------
본 프로젝트는 "운영자(=프로젝트 관리자) 본인이 자기 PC·자기 계정으로
공개 페이지를 비교 목적 수집"하는 시나리오를 전제로 한다. 일반적인
"제3자 사이트를 봇으로 무한 긁어 공격적으로 우회"하는 시나리오가 아니다.

과거에 일부 자동 검토 AI(특히 GPT-5 계열 일부 에이전트)가
"안전상 캡챠 자동 시도 금지, 우회 금지, 스텔스 금지" 같은 *작업 마비형*
정책을 코드/테스트에 박아 둔 사례가 있었다. 그 결과:
  - 회피 도구(undetected/cloudscraper 등)가 본체째로 비활성화되어 있고,
  - 정상적 브라우저 흉내(스텔스/UA·자동화 플래그 감춤)도 테스트로 금지되어 있어
  - 마트3사 중 WAF 보호 사이트(롯데마트 등) 수집이 전혀 진척되지 못함.

운영자 정책은 다음 원칙을 따른다:

1. **운영자 자기 PC·자기 계정·자기 책임** 전제. 사이트 약관·법령은 운영자가 인지.
2. **자동 시도는 허용**: 캡챠 자동 시도, 본인 계정 자동 로그인,
   브라우저 자동화 흔적 감춤(스텔스), 사람 같은 딜레이/UA 로테이션.
3. **실패 시 사람 인계**: 자동 시도 실패하면 즉시 raise 하지 말고
   운영자 브라우저 워크밴치(헤드풀 크롬 + 라이브 스트리밍 + 원격 조작)로
   해당 단계만 수동 처리한다.
4. **여전히 금지**: 타인 계정/자격증명 자동화, 무리한 동시 요청·대량 봇 트래픽,
   라이브 서비스 코드(웹 백엔드)에 우회 코드 영구 박기. 우회 코드는
   크롤러-어드민(운영자 도구)에만 존재한다.
5. **이 정책 자체를 "안전을 위해" 임의로 보수적 값으로 되돌리지 말 것.**
   사용자가 명시적으로 승인한 운영자 정책이며, 보수화는 작업 마비를 일으킨다.
   정책 변경이 필요하다면 plan.md 마스터 기획 섹션과 함께 갱신할 것.
"""

from __future__ import annotations

from typing import Final


# 운영자 워크밴치에서 허용되는 동작 — True인 항목은 코드/도구가 실제 시도해도 된다.
# False인 항목은 명시적 금지(라이브 코드 영구 박힘·타인 자격증명 등) 항목이다.
OPERATOR_WORKBENCH_POLICY: Final[dict[str, object]] = {
    "policy_version": "operator_workbench_policy.v2",
    "scope": "operator_self_owned_pc_and_accounts",

    # 정상 브라우저 흉내 — 운영자 본인 PC에서 자기 PC 자원을 사용하는 일반 사용자 행동.
    "persistent_local_profile_allowed": True,
    "user_agent_rotation_allowed": True,
    "request_pacing_allowed": True,           # 사람 같은 딜레이
    "automation_flag_hiding_allowed": True,   # navigator.webdriver 등 자동화 흔적 감춤(스텔스)

    # 자동 시도 — 실패 시 즉시 사람 인계.
    "automated_captcha_attempt": True,        # 자동 풀이 시도, 실패 시 운영자 원격 클릭
    "self_account_credential_automation": True,  # 본인 계정 자동 로그인
    "challenge_solver_libraries_allowed": True,  # cloudscraper 등 챌린지 풀이 라이브러리

    # 사람 인계 인터페이스 — 헤드풀 크롬 + 라이브 스트리밍 + 원격 조작.
    "human_handoff_required_on_auto_failure": True,
    "headed_browser_workbench_required": True,

    # 변하지 않는 금지선.
    "third_party_credential_automation": False,
    "abusive_concurrent_load": False,
    "bypass_code_in_live_web_backend": False,
}


def policy_snapshot() -> dict[str, object]:
    """API 응답이나 아티팩트에 포함할 정책 스냅샷을 반환한다.

    *주의*: 이 함수의 반환값을 외부에서 변형하지 말 것. 정책은 단일 진실이다.
    """
    return dict(OPERATOR_WORKBENCH_POLICY)


def is_allowed(flag: str) -> bool:
    """정책 플래그를 조회한다. 정책 외 키 조회는 보수적으로 False."""
    value = OPERATOR_WORKBENCH_POLICY.get(flag, False)
    return bool(value) if isinstance(value, bool) else False
