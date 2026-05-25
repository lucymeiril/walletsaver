// web-FINAL §10: iframe 슬롯 + postMessage 4종 컨텍스트 계약.
// 의도: 사용자 자체 개조(플러그인) 자리. sandbox 로 격리, 4종 메시지(ready/resize/navigate/request_context).
//       기본 접힘 카드 → "외부 위젯 열기" 클릭 시 lazy load. 화이트리스트 외 origin 무시.
// 후속 AI에게: postMessage 종류 함부로 추가하지 말 것. 4종이 합의된 계약.

import { useEffect, useRef, useState } from 'react'

export type PluginContext =
  | {
      slot: 'product_detail'
      canonical_id: string
      product_name: string
      displayed_price: number | null
      p50: number | null
      grade: string
    }
  | {
      slot: 'account_sidebar'
      favorite_count: number
      recent_count: number
    }

interface PluginSlotProps {
  src: string
  title: string
  context: PluginContext
  minHeight?: number
  maxHeight?: number
  allowedOrigins?: string[]
  navigateAllowList?: string[]
  onNavigate?: (url: string) => void
}

export function PluginSlot({
  src,
  title,
  context,
  minHeight = 320,
  maxHeight = 720,
  allowedOrigins,
  navigateAllowList = [],
  onNavigate,
}: PluginSlotProps) {
  const [open, setOpen] = useState(false)
  const [height, setHeight] = useState(minHeight)
  const [errored, setErrored] = useState(false)
  const iframeRef = useRef<HTMLIFrameElement | null>(null)

  useEffect(() => {
    if (!open) return
    function originAllowed(origin: string): boolean {
      if (!allowedOrigins || allowedOrigins.length === 0) return true
      return allowedOrigins.includes(origin)
    }
    function handle(ev: MessageEvent) {
      if (!iframeRef.current || ev.source !== iframeRef.current.contentWindow) return
      if (!originAllowed(ev.origin)) return
      const msg = ev.data as { type?: string } & Record<string, unknown>
      if (!msg || typeof msg !== 'object') return
      const t = msg.type
      if (t === 'ready') {
        iframeRef.current.contentWindow?.postMessage({ type: 'context', context }, '*')
      } else if (t === 'request_context') {
        iframeRef.current.contentWindow?.postMessage({ type: 'context', context }, '*')
      } else if (t === 'resize') {
        const h = Number(msg.height)
        if (Number.isFinite(h)) {
          setHeight(Math.max(minHeight, Math.min(maxHeight, Math.round(h))))
        }
      } else if (t === 'navigate') {
        const url = typeof msg.url === 'string' ? msg.url : ''
        if (!url) return
        const inList = navigateAllowList.some((u) => url.startsWith(u))
        if (inList) onNavigate?.(url)
      }
    }
    window.addEventListener('message', handle)
    return () => window.removeEventListener('message', handle)
  }, [open, context, minHeight, maxHeight, allowedOrigins, navigateAllowList, onNavigate])

  if (!open) {
    return (
      <section
        data-testid="plugin-slot"
        data-slot={context.slot}
        data-open="false"
        style={{
          border: '1px dashed #d1d5db',
          borderRadius: 12,
          padding: 12,
          margin: '16px 0',
          background: '#f9fafb',
          textAlign: 'center',
        }}
      >
        <strong style={{ fontSize: 14 }}>{title}</strong>
        <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>외부 위젯 (사용자 자체 개조)</div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          style={{
            marginTop: 10,
            padding: '6px 14px',
            borderRadius: 8,
            border: '1px solid #d1d5db',
            background: 'white',
            cursor: 'pointer',
          }}
        >
          외부 위젯 열기
        </button>
      </section>
    )
  }

  return (
    <section
      data-testid="plugin-slot"
      data-slot={context.slot}
      data-open="true"
      style={{ border: '1px solid #e5e7eb', borderRadius: 12, padding: 4, margin: '16px 0' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', padding: '4px 8px' }}>
        <strong style={{ fontSize: 13 }}>{title}</strong>
        <span style={{ flex: 1 }} />
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="위젯 닫기"
          style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#6b7280' }}
        >
          ×
        </button>
      </div>
      {errored ? (
        <div style={{ padding: 24, textAlign: 'center', color: '#6b7280' }}>
          위젯을 불러오지 못했습니다.{' '}
          <button
            type="button"
            onClick={() => setErrored(false)}
            style={{ marginLeft: 8 }}
          >
            재시도
          </button>
        </div>
      ) : (
        <iframe
          ref={iframeRef}
          src={src}
          title={title}
          sandbox="allow-scripts allow-same-origin"
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setErrored(true)}
          style={{ border: 0, width: '100%', height }}
          data-testid="plugin-iframe"
        />
      )}
    </section>
  )
}
