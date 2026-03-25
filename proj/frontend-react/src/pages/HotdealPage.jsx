import { useState } from 'react';
import { HOTDEALS, HOTDEAL_FILTERS, fmt } from '../data/mockData';
import s from './HotdealPage.module.css';

export default function HotdealPage() {
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('time');

  let items = filter === 'all' ? [...HOTDEALS] : HOTDEALS.filter(d => d.cat === filter);
  if (sort === 'discount') items.sort((a,b) => {
    const ra = a.price && a.origPrice ? a.price/a.origPrice : 1;
    const rb = b.price && b.origPrice ? b.price/b.origPrice : 1;
    return ra - rb;
  });
  if (sort === 'popular') items.sort((a,b) => b.views - a.views);

  return (
    <div>
      <div className={s.hdr}><h2>핫딜 모아보기</h2><p>뽐뿌 · 어미새 · 루리웹 · 에펨코리아 · 무신사 핫딜과 자동 가격 판단</p></div>
      <div className={s.controls}>
        <div className={s.filters}>
          {HOTDEAL_FILTERS.map(f => <button key={f.key} className={`${s.fbtn} ${filter === f.key ? s.fbtnActive : ''}`} onClick={() => setFilter(f.key)}>{f.label}</button>)}
        </div>
        <select className={s.sortSel} value={sort} onChange={e => setSort(e.target.value)}>
          <option value="time">최신순</option><option value="discount">할인율순</option><option value="popular">인기순</option>
        </select>
      </div>
      <div className={s.grid}>
        {items.map(d => (
          <div key={d.id} className={s.card}>
            {d.thumb && <img src={d.thumb} alt={d.title} className={s.thumb} loading="lazy" />}
            <div className={s.cardBody}>
              <div className={s.cardHead}><span className={s.source}>{d.source}</span><span className={s.time}>{d.time}</span></div>
              <div className={s.cardTitle}>{d.title}</div>
              <div className={s.cardBottom}>
                <span className={s.price}>{d.price ? `${fmt(d.price)}원` : ''}</span>
                {d.price && d.origPrice && (
                  <span className={`${s.badge} ${d.price/d.origPrice <= 0.5 ? s.ultra : d.price/d.origPrice <= 0.75 ? s.great : s.ok}`}>
                    {Math.round((1-d.price/d.origPrice)*100)}% 할인
                  </span>
                )}
              </div>
              <div className={s.cardMeta}>👁️ {d.views} · 💬 {d.comments}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
