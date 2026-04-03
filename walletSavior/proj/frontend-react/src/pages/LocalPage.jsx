import { useState } from 'react';
import { MapPin, Fuel } from 'lucide-react';
import { GAS_STATIONS, RESTAURANTS, LOCAL_AVGS, fmt } from '../data/mockData';
import s from './LocalPage.module.css';

export default function LocalPage() {
  const [tab, setTab] = useState('gas');
  const [fuel, setFuel] = useState('gasoline');
  const [restCat, setRestCat] = useState('all');

  const sorted = [...GAS_STATIONS].sort((a,b) => (a[fuel]||9999) - (b[fuel]||9999));
  const validGas = sorted.filter(g => g[fuel]);
  const avgGas = validGas.length ? Math.round(validGas.reduce((s,g) => s + g[fuel], 0) / validGas.length) : 0;

  const filteredRest = restCat === 'all' ? RESTAURANTS : RESTAURANTS.filter(r => r.cat === restCat);

  return (
    <div>
      <div className={s.hdr}><h2>우리 동네 물가 지도</h2><p>주유소 및 식당/카페 평균 가격을 비교하세요</p></div>
      <div className={s.layout}>
        <div className={s.map}>
          <div className={s.mapPlaceholder}>
            <MapPin size={48} strokeWidth={1.2} />
            <p>지도 API 연결 시 위치가 표시됩니다</p>
            <span className={s.mapTag}>Kakao Maps / Naver Maps API 연동 예정</span>
          </div>
        </div>
        <div className={s.sidebar}>
          <div className={s.mainToggle}>
            <button className={`${s.toggleBtn} ${tab === 'gas' ? s.toggleActive : ''}`} onClick={() => setTab('gas')}>⛽ 주유소</button>
            <button className={`${s.toggleBtn} ${tab === 'rest' ? s.toggleActive : ''}`} onClick={() => setTab('rest')}>🍽️ 동네 식당</button>
          </div>

          {tab === 'gas' ? (
            <>
              <div className={s.fuelToggle}>
                {[['gasoline','휘발유'],['diesel','경유'],['lpg','LPG']].map(([k,l]) => (
                  <button key={k} className={`${s.fuelBtn} ${fuel === k ? s.fuelActive : ''}`} onClick={() => setFuel(k)}>{l}</button>
                ))}
              </div>
              <div className={s.list}>
                {validGas.map((g,i) => (
                  <div key={i} className={s.item}>
                    <span className={s.rank}>{i+1}</span>
                    <div className={s.itemBody}>
                      <div className={s.itemName}>{g.name}</div>
                      <div className={s.itemAddr}>{g.addr}</div>
                    </div>
                    <span className={s.itemPrice}>{fmt(g[fuel])}원</span>
                  </div>
                ))}
              </div>
              <div className={s.avg}><span>전국 평균</span><strong>{fmt(avgGas)}원/L</strong></div>
            </>
          ) : (
            <>
              <div className={s.fuelToggle}>
                {['all','한식','중식','카페'].map(c => (
                  <button key={c} className={`${s.fuelBtn} ${restCat === c ? s.fuelActive : ''}`} onClick={() => setRestCat(c)}>{c === 'all' ? '전체' : c}</button>
                ))}
              </div>
              <div className={s.list}>
                {filteredRest.map((r,i) => {
                  const avg = LOCAL_AVGS[r.menu];
                  const diff = avg ? r.price - avg : null;
                  return (
                    <div key={i} className={s.item}>
                      <div className={s.itemBody}>
                        <div className={s.itemName}>{r.name}</div>
                        <div className={s.itemAddr}>{r.menu} · ⭐ {r.rating}</div>
                      </div>
                      <div style={{textAlign:'right'}}>
                        <span className={s.itemPrice}>{fmt(r.price)}원</span>
                        {diff !== null && <div className={s.itemVs} style={{color: diff <= 0 ? 'var(--green)' : 'var(--red)', fontSize:'.72rem'}}>
                          시세 대비 {diff <= 0 ? fmt(diff) : `+${fmt(diff)}`}원
                        </div>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
