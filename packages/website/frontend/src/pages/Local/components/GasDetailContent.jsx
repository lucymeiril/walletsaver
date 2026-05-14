import { fmt } from '../../../data/mockData';
import s from '../LocalPage.module.css';

export default function GasDetailContent({ station, avgGas, avgGasoline, avgDiesel, onFocusMap }) {
  const isSelf = station.is_self || station.name.includes('셀프');
  const dist = station.distance != null
    ? (parseFloat(station.distance) > 100
        ? (parseFloat(station.distance) / 1000).toFixed(1)
        : parseFloat(station.distance).toFixed(1))
    : (station.idx != null ? (0.5 + station.idx * 0.3).toFixed(1) : '?');

  const fuelRows = [
    { label: '휘발유', key: 'gasoline', avg: avgGasoline || avgGas },
    { label: '고급 휘발유', key: 'premium_gasoline', avg: Math.round((avgGasoline || avgGas) * 1.15) },
    { label: '경유', key: 'diesel', avg: avgDiesel || Math.round(avgGas * 0.9) },
    { label: 'LPG', key: 'lpg', avg: Math.round((avgGasoline || avgGas) * 0.62) },
  ];

  return (
    <div className={s.modalDetail}>
      <div className={s.detailHeader}>
        <h3 className={s.detailName}>{station.name}</h3>
        {station.brand && <span className={s.detailBrand}>{station.brand}</span>}
        {isSelf && <span className={s.selfTag}>셀프</span>}
        {station.is_24h && <span className={s.selfTag}>24h</span>}
      </div>
      <p className={s.detailAddr}>📍 {station.addr || station.address}</p>
      {station.tel && (
        <p className={s.detailTel}>
          📞 <a href={`tel:${station.tel}`} className={s.telLink}>{station.tel}</a>
        </p>
      )}
      <p className={s.detailDist}>📏 현재 위치에서 ~{dist}km</p>

      <div className={s.detailSection}>
        <h4>⛽ 유종별 가격</h4>
        <div className={s.fuelTable}>
          {fuelRows.map(f => {
            const price = station[f.key];
            if (!price) return (
              <div key={f.key} className={s.fuelRow}>
                <span className={s.fuelLabel}>{f.label}</span>
                <span className={s.fuelNA}>취급 안 함</span>
              </div>
            );
            const diff = price - f.avg;
            return (
              <div key={f.key} className={s.fuelRow}>
                <span className={s.fuelLabel}>{f.label}</span>
                <span className={s.fuelPrice}>{fmt(price)}원/L</span>
                {f.avg > 0 && (
                  <span className={s.fuelDiff} style={{ color: diff <= 0 ? 'var(--green)' : 'var(--red)' }}>
                    지역 평균 대비 {diff <= 0 ? fmt(diff) : `+${fmt(diff)}`}원
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className={s.detailSection}>
        <h4>ℹ️ 운영 정보</h4>
        <div className={s.infoGrid}>
          <div className={s.infoItem}>
            <span className={s.infoLabel}>셀프 여부</span>
            <span className={s.infoValue}>{isSelf ? '✅ 셀프 주유' : '❌ 일반 주유'}</span>
          </div>
          <div className={s.infoItem}>
            <span className={s.infoLabel}>운영 시간</span>
            <span className={s.infoValue}>{station.is_24h ? '24시간' : '06:00 ~ 23:00'}</span>
          </div>
          {station.has_car_wash && (
            <div className={s.infoItem}>
              <span className={s.infoLabel}>세차장</span>
              <span className={s.infoValue}>✅ 있음</span>
            </div>
          )}
          {station.brand && (
            <div className={s.infoItem}>
              <span className={s.infoLabel}>브랜드</span>
              <span className={s.infoValue}>{station.brand}</span>
            </div>
          )}
        </div>
      </div>

      <div className={s.btnGroup}>
        <button className={s.mapFocusBtn} onClick={() => onFocusMap(station.name)}>
          🗺️ 지도에서 위치 보기
        </button>
        {station.naverUrl && (
          <a href={station.naverUrl} target="_blank" rel="noopener noreferrer" className={s.naverLinkBtn}>
            📍 네이버 지도에서 보기 →
          </a>
        )}
      </div>
    </div>
  );
}
