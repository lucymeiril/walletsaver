import { useParams } from 'react-router-dom';
import { useMemo, useState } from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { Heart } from 'lucide-react';
import { MARTS } from '../utils/constants';
import { fmt } from '../utils/helpers';
import useStore from '../stores/appStore';
import ShareButton from '../components/common/ShareButton';
import s from './PricePage.module.css';

export default function PricePage() {
  const { id } = useParams();
  const { selectedProduct, addFavorite, removeFavorite, isFavorite } = useStore();
  const [range, setRange] = useState(30);
  const [variantIdx, setVariantIdx] = useState(0);

  const product = id
    ? PRODUCTS.find(p => p.id === Number(id))
    : selectedProduct || PRODUCTS[0];

  const chartData = useMemo(() => product ? genPriceHistory(product, range) : [], [product, range]);

  if (!product) return <div className={s.empty}>상품을 검색해보세요</div>;

  // 속성 변형 (냉장/냉동/국산/수입 등)
  const variants = PRODUCT_VARIANTS[product.id] || [];
  const activeVariant = variants[variantIdx] || null;
  const displayAvg  = activeVariant?.avg  ?? product.avg;
  const displayCur  = activeVariant?.cur  ?? product.cur;
  const displayLow  = activeVariant?.low  ?? product.low;
  const displayHigh = activeVariant?.high ?? product.high;

  const ratio = displayCur / displayAvg;
  const diff = displayCur - displayAvg;

  let timing = {};
  if (ratio <= 0.7)       timing = { cls: 'ultra', icon: '🔥', title: '역대급 기회!',       desc: `현재 ${fmt(displayCur)}원은 평균보다 ${Math.round((1-ratio)*100)}% 저렴합니다.` };
  else if (ratio <= 0.85) timing = { cls: 'great', icon: '💙', title: '좋은 가격이에요!',   desc: `현재 ${fmt(displayCur)}원은 평균(${fmt(displayAvg)}원)보다 ${Math.round((1-ratio)*100)}% 저렴합니다.` };
  else if (ratio <= 1.05) timing = { cls: 'good',  icon: '✅', title: '지금 사도 괜찮아요!', desc: `현재 ${fmt(displayCur)}원은 평균(${fmt(displayAvg)}원) 수준입니다. (${diff >= 0 ? '+' : ''}${fmt(diff)}원)` };
  else                    timing = { cls: 'wait',  icon: '⏳', title: '조금 기다려보세요',   desc: `현재 ${fmt(displayCur)}원은 평균보다 ${Math.round((ratio-1)*100)}% 비쌉니다.` };

  const tierPos = Math.max(3, Math.min(97, ((displayCur - displayLow) / (displayHigh - displayLow)) * 100));

  return (
    <div>
      <div className={s.hdr}><h2>물가 비교</h2><p>정부 공식 + 마트 전단 기반 — 진짜 적정 가격을 확인하세요</p></div>
      <div className={s.layout}>
        <div className={s.left}>
          {/* 상품 정보 */}
          <div className={s.itemInfo}>
            <span className={s.icon}>{product.icon}</span>
            <div><h3>{product.name} {product.unit}</h3><span className={s.cat}>{product.cat}</span></div>
            <button
              className={`${s.favBtn} ${isFavorite(product.id) ? s.favActive : ''}`}
              onClick={() => isFavorite(product.id) ? removeFavorite(product.id) : addFavorite(product.id)}
              title={isFavorite(product.id) ? '관심 해제' : '관심 등록'}
            >
              <Heart size={20} fill={isFavorite(product.id) ? 'currentColor' : 'none'} />
            </button>
            <div className={s.shareWrap}>
              <ShareButton
                type="button"
                title={`${product.name} 가격 비교`}
                text={`[지갑지키미] ${product.name} 현재 ${fmt(product.cur)}원 — 평균 대비 ${Math.abs(Math.round((1 - product.cur / product.avg) * 100))}% ${product.cur <= product.avg ? '저렴' : '비쌈'}!`}
                url={`${window.location.origin}/price/${product.id}`}
              />
            </div>
          </div>

          {/* 속성 변형 선택 (냉장/냉동/국산/수입 등) */}
          {variants.length > 0 && (
            <div className={s.variantSec}>
              <span className={s.variantLabel}>속성 분류</span>
              <div className={s.variantChips}>
                {variants.map((v, i) => (
                  <button key={i} className={`${s.variantChip} ${variantIdx === i ? s.variantActive : ''}`} onClick={() => setVariantIdx(i)}>
                    {v.label}
                    {v.storage !== '-' && <span className={s.variantTag}>{v.storage}</span>}
                    {v.grade !== '-' && v.grade !== '1등급' && <span className={s.variantTag}>{v.grade}</span>}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 타이밍 뱃지 */}
          <div className={`${s.timing} ${s[timing.cls]}`}>
            <span className={s.timingIcon}>{timing.icon}</span>
            <div><strong>{timing.title}</strong><p>{timing.desc}</p></div>
          </div>

          {/* 가격 박스 4칸 */}
          <div className={s.prices}>
            <div className={`${s.priceBox} ${s.current}`}><span className={s.label}>현재 평균</span><span className={s.val}>{fmt(displayCur)}원</span></div>
            <div className={s.priceBox}><span className={s.label}>30일 평균</span><span className={s.val}>{fmt(displayAvg)}원</span></div>
            <div className={`${s.priceBox} ${s.low}`}><span className={s.label}>최근 최저</span><span className={s.val}>{fmt(displayLow)}원</span></div>
            <div className={`${s.priceBox} ${s.high}`}><span className={s.label}>최근 최고</span><span className={s.val}>{fmt(displayHigh)}원</span></div>
          </div>

          {/* 가격 등급 바 */}
          <div className={s.tierBar}>
            <div className={s.tierLabel}>가격 등급</div>
            <div className={s.tierTrack}>
              <div className={`${s.zone} ${s.zoneUltra}`} style={{width:'15%'}}>역대급</div>
              <div className={`${s.zone} ${s.zoneGreat}`} style={{width:'20%'}}>좋은 가격</div>
              <div className={`${s.zone} ${s.zoneOk}`} style={{width:'30%'}}>평균 수준</div>
              <div className={`${s.zone} ${s.zoneWait}`} style={{width:'20%'}}>조금 비쌈</div>
              <div className={`${s.zone} ${s.zoneBad}`} style={{width:'15%'}}>비쌈</div>
              <div className={s.marker} style={{left:`${tierPos}%`}} />
            </div>
          </div>

          {/* 차트 */}
          <div className={s.chartBox}>
            <div className={s.chartHead}>
              <h4>{range}일 가격 추이</h4>
              <div className={s.chartBtns}>
                {[30,90,365].map(r => (
                  <button key={r} className={`${s.chartBtn} ${range === r ? s.chartBtnActive : ''}`} onClick={() => setRange(r)}>
                    {r === 365 ? '1년' : `${r}일`}
                  </button>
                ))}
              </div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" tick={{fill:'#64748b', fontSize:11}} axisLine={false} tickLine={false} />
                <YAxis tick={{fill:'#64748b', fontSize:11}} axisLine={false} tickLine={false} width={50} tickFormatter={v => fmt(v)} />
                <Tooltip
                  contentStyle={{background:'var(--surface)', border:'1px solid var(--border)', borderRadius:8, fontSize:'.85rem'}}
                  formatter={v => [`${fmt(v)}원`, '가격']}
                />
                <Area type="monotone" dataKey="price" stroke="#38bdf8" strokeWidth={2} fill="url(#colorPrice)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* 상세 통계 */}
          <details className={s.details}>
            <summary>상세 통계 보기</summary>
            <div className={s.statsGrid}>
              <div className={s.stat}><span className={s.statLabel}>평균 할인율</span><span className={s.statVal}>22.4%</span></div>
              <div className={s.stat}><span className={s.statLabel}>할인 빈도</span><span className={s.statVal}>월 2.3회</span></div>
              <div className={s.stat}><span className={s.statLabel}>최저가 주기</span><span className={s.statVal}>약 45일</span></div>
              <div className={s.stat}><span className={s.statLabel}>다음 예상 최저</span><span className={s.statVal}>~4월 초</span></div>
              <div className={s.stat}><span className={s.statLabel}>데이터 기간</span><span className={s.statVal}>180일</span></div>
              <div className={s.stat}><span className={s.statLabel}>수집 레코드</span><span className={s.statVal}>1,247건</span></div>
            </div>
          </details>
        </div>

        {/* 우측 사이드바 */}
        <aside className={s.right}>
          <h4>마트별 현재 가격</h4>
          <div className={s.martList}>
            {MARTS.map(m => {
              const price = product.stores[m.key];
              const d = price - product.avg;
              return (
                <div key={m.key} className={s.mlItem}>
                  <div className={s.mlLeft}>
                    <span className={s.mlDot} style={{background:m.color}} />
                    <span className={s.mlName}>{m.name}</span>
                  </div>
                  <div>
                    <span className={s.mlPrice}>{fmt(price)}원</span>
                    <span className={`${s.mlVs} ${d <= 0 ? s.cheap : s.expensive}`}>
                      {d <= 0 ? fmt(d) : `+${fmt(d)}`}원
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          <h4>관련 핫딜</h4>
          <div className={s.relatedDeals}>
            {HOTDEALS.filter(d => d.cat === 'food').slice(0, 3).map(d => (
              <div key={d.id} className={s.rdItem}>
                <div className={s.rdTitle}>{d.title}</div>
                <div className={s.rdMeta}><span>{d.source}</span><span>{d.time}</span></div>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
