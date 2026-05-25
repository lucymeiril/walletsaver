// web-FINAL §6-1: 초심자/핫딜러 모드 토글.
// 의도: 상품 상세 3계층 초기 펼침 상태와 카드 표시 밀도를 모드 단일 축으로 분기.
// localStorage 키 `wsf_mode` 로 저장 → 다음 방문 시 복원. (서버 동기화는 P1, 자리만)
// 후속 AI에게: 모드 분기를 컴포넌트 내부 ad-hoc state 로 만들지 말 것. 일관성 깨짐.

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type UserMode = 'beginner' | 'pro'
const STORAGE_KEY = 'wsf_mode'

interface ModeCtx {
  mode: UserMode
  setMode: (m: UserMode) => void
  toggle: () => void
}

const ModeContext = createContext<ModeCtx>({
  mode: 'beginner',
  setMode: () => {},
  toggle: () => {},
})

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<UserMode>(() => {
    if (typeof window === 'undefined') return 'beginner'
    const stored = window.localStorage?.getItem(STORAGE_KEY)
    return stored === 'pro' ? 'pro' : 'beginner'
  })

  useEffect(() => {
    try {
      window.localStorage?.setItem(STORAGE_KEY, mode)
    } catch {
      /* private mode etc — non-fatal */
    }
  }, [mode])

  return (
    <ModeContext.Provider
      value={{
        mode,
        setMode: setModeState,
        toggle: () => setModeState((m) => (m === 'pro' ? 'beginner' : 'pro')),
      }}
    >
      {children}
    </ModeContext.Provider>
  )
}

export function useMode() {
  return useContext(ModeContext)
}
