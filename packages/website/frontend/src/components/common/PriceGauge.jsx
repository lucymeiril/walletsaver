/**
 * PriceGauge — 현재 가격을 시장 분위수 기준으로 시각화.
 *
 * displayPrice = product.current_low ?? product.p10
 * p50 폴백은 사용하지 않음 (회귀 방지).
 */

function getGaugePosition(displayPrice, p10, p50, p90) {
  if (!displayPrice || !p10 || !p90 || p90 <= p10) return null;
  const clamped = Math.max(p10, Math.min(p90, displayPrice));
  return ((clamped - p10) / (p90 - p10)) * 100;
}

function getPriceLabel(displayPrice, p10, p50, p90) {
  if (!displayPrice) return { text: '가격 정보 없음', color: '#888' };
  if (p10 && displayPrice <= p10) return { text: '역대 최저가 수준', color: '#137333' };
  if (p50 && displayPrice <= p50) return { text: '평균 이하 저렴', color: '#1a73e8' };
  if (p90 && displayPrice >= p90) return { text: '비싼 편', color: '#c62828' };
  return { text: '평균 수준', color: '#555' };
}

function fmt(v) {
  if (v == null) return '-';
  return `${Number(v).toLocaleString('ko-KR')}원`;
}

export default function PriceGauge({ product }) {
  if (!product) return null;

  // displayPrice = current_low ?? p10 (p50 폴백 금지)
  const displayPrice = product.current_low ?? product.p10;
  const { p10, p50, p90 } = product;

  const position = getGaugePosition(displayPrice, p10, p50, p90);
  const label = getPriceLabel(displayPrice, p10, p50, p90);

  return (
    <div
      style={{
        padding: '12px 16px',
        background: '#f8f9fa',
        borderRadius: 10,
        marginTop: 8,
      }}
      aria-label="가격 게이지"
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>가격 위치</span>
        <span style={{ fontWeight: 700, color: label.color, fontSize: 14 }}>{label.text}</span>
      </div>

      {/* 게이지 바 */}
      <div
        style={{
          position: 'relative',
          height: 8,
          background: 'linear-gradient(to right, #137333, #1a73e8, #f9a825, #c62828)',
          borderRadius: 4,
          marginBottom: 4,
        }}
      >
        {position != null && (
          <div
            style={{
              position: 'absolute',
              top: -4,
              left: `${position}%`,
              transform: 'translateX(-50%)',
              width: 16,
              height: 16,
              background: '#fff',
              border: '2px solid #333',
              borderRadius: '50%',
            }}
            aria-label={`현재 위치: ${Math.round(position)}%`}
          />
        )}
      </div>

      {/* 분위수 레이블 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#888' }}>
        <span>최저 {fmt(p10)}</span>
        {p50 && <span>중간 {fmt(p50)}</span>}
        <span>최고 {fmt(p90)}</span>
      </div>

      {displayPrice != null && (
        <div style={{ marginTop: 6, fontSize: 13, color: '#333' }}>
          현재 표시 가격: <strong>{fmt(displayPrice)}</strong>
        </div>
      )}
    </div>
  );
}
