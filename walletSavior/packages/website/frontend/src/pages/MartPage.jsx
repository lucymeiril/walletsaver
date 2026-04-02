import { useState } from 'react';
import { MARTS } from '../utils/constants';
import { fmt } from '../utils/helpers';
import s from './MartPage.module.css';

export default function MartPage() {
  const [activeMart, setActiveMart] = useState('emart');
  const mart = MART_DATA[activeMart];

  return (
    <div>
      <div className={s.hdr}><h2>마트 할인 전단</h2><p>이마트 · 홈플러스 · 롯데마트 · 코스트코 이번 주 할인</p></div>
      <div className={s.tabs}>
        {MARTS.map(m => (
          <button key={m.key} className={`${s.tab} ${activeMart === m.key ? s.tabActive : ''}`} onClick={() => setActiveMart(m.key)}>
            <span className={s.dot} style={{background:m.color}} />{m.name}
          </button>
        ))}
      </div>
      <div className={s.info}><span>행사 기간: {mart.period}</span><span>총 {mart.items.length}개 상품</span></div>
      <div className={s.grid}>
        {mart.items.map((item, i) => {
          const matched = PRODUCTS.find(p => item.name.includes(p.name));
          const diff = matched ? item.sale - matched.avg : null;
          return (
            <div key={i} className={s.card}>
              <div className={s.cardName}>{item.name}</div>
              <div className={s.cardPrices}>
                <span className={s.sale}>{fmt(item.sale)}원</span>
                <span className={s.orig}>{fmt(item.orig)}원</span>
                <span className={s.disc}>-{item.disc}%</span>
              </div>
              {diff !== null && (
                <div className={s.vs}>DB 평균 대비 <em className={diff <= 0 ? s.cheap : s.expensive}>{diff <= 0 ? fmt(diff) : `+${fmt(diff)}`}원</em></div>
              )}
              <span className={s.event}>{item.event}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
