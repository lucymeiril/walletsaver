import { fmt } from '../../../utils/helpers';
import s from '../LocalPage.module.css';

export default function GasDetailContent({ station, avgGas, avgGasoline, avgDiesel, onFocusMap }) {
  const isSelf = station.is_self || station.name.includes('셀프');
  const dist = station.distance != null
    ? (parseFloat(station.distance) > 100
        ? (parseFloat(station.distance) / 1000).toFixed(1)
        : parseFloat(station.distance).toFixed(1))
    : null;

  const fuelRows = [
    { label: '휘발유', key: 'gasoline', avg: avgGasoline || avgGas },
    { label: '고급 휘발유', key: 'premium_gasoline', avg: 0 },
    { label: '경유', key: 'diesel', avg: avgDiesel || 0 },
    { label: 'LPG', key: 'lpg', avg: 0 },
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
      {dist != null && <p className={s.detailDist}>📏 현재 위치에서 약 {dist}km</p>}
      {station.updated_at && (
        <p className={s.detailTel}>🕒 가격 갱신 {String(station.updated_at).slice(0, 16)}</p>
      )}

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
            <span className={s.infoValue}>{station.is_24h ? '24시간' : '운영 시간 미확인'}</span>
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

      <p className={s.detailTel}>
        {String(station.source || '').startsWith('opinet') ? (
          <>출처: <a href="https://www.opinet.co.kr/searRgOsSelect.do" target="_blank" rel="noopener noreferrer" className={s.telLink}>오피넷 공개 가격정보</a></>
        ) : (
          <>출처: {station.source || '외부 지도 검색 결과'}</>
        )}
        {' '}· 특정 시점 관측값으로 실제 판매가와 다를 수 있습니다.
      </p>

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
