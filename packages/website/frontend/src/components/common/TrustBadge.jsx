/**
 * TrustBadge — 판매자·상품 신뢰 등급 배지.
 * kind: 'official' | 'verified' | 'caution'
 * variant: 'card' (소형) | 'detail' (확장)
 */

const KIND_CONFIG = {
  official: {
    label: '공식',
    icon: '🏛️',
    description: '정부 또는 공인 기관이 직접 검증한 판매처',
    color: '#1a73e8',
    bg: '#e8f0fe',
  },
  verified: {
    label: '검증',
    icon: '✅',
    description: 'WalletSavior 자체 검증을 통과한 판매처',
    color: '#137333',
    bg: '#e6f4ea',
  },
  caution: {
    label: '주의',
    icon: '⚠️',
    description: '가격 신뢰도 이슈가 보고된 판매처 — 구매 전 확인 권장',
    color: '#b06000',
    bg: '#fef7e0',
  },
};

export default function TrustBadge({ kind, variant = 'card' }) {
  const cfg = KIND_CONFIG[kind];
  if (!cfg) return null;

  if (variant === 'detail') {
    return (
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'flex-start',
          gap: 8,
          padding: '8px 12px',
          borderRadius: 8,
          background: cfg.bg,
          border: `1px solid ${cfg.color}33`,
        }}
        aria-label={`신뢰 등급: ${cfg.label}`}
      >
        <span style={{ fontSize: 18 }}>{cfg.icon}</span>
        <div>
          <div style={{ fontWeight: 700, color: cfg.color, fontSize: 13 }}>{cfg.label}</div>
          <div style={{ fontSize: 12, color: '#555', marginTop: 2 }}>{cfg.description}</div>
        </div>
      </div>
    );
  }

  // variant === 'card'
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 12,
        background: cfg.bg,
        color: cfg.color,
        fontWeight: 600,
        fontSize: 12,
        border: `1px solid ${cfg.color}44`,
      }}
      aria-label={`신뢰 등급: ${cfg.label}`}
    >
      {cfg.icon} {cfg.label}
    </span>
  );
}
