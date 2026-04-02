import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X, TrendingUp, TrendingDown, Minus, ArrowRight, Heart, Clock } from 'lucide-react';
import { MARTS } from '../utils/constants';
import { fmt } from '../utils/helpers';
import useStore from '../stores/appStore';
import RecipeCalculator from '../components/features/RecipeCalculator';
import FavoritesDashboard from '../components/features/FavoritesDashboard';
import ShareButton from '../components/common/ShareButton';
import s from './HomePage.module.css';

const TRENDING = ['삼겹살', '계란 30구', '양파 특가', '코스트코', '우유 1L', '라면 5입', '휘발유', '사과'];

export default function HomePage() {
  const navigate = useNavigate();
  const { setSelectedProduct, favorites, addFavorite, removeFavorite, isFavorite, recentSearches, addRecentSearch, clearRecentSearches } = useStore();

  // 검색
  const [query, setQuery] = useState('');
  const [acOpen, setAcOpen] = useState(false);
  const inputRef = useRef(null);

  const matches = query.length > 0
    ? PRODUCTS.filter(p => p.name.includes(query) || p.cat.includes(query))
    : [];

  const selectProduct = useCallback((p) => {
    setSelectedProduct(p);
    addRecentSearch(p.name);
    setQuery('');
    setAcOpen(false);
    navigate(`/price/${p.id}`);
  }, [navigate, setSelectedProduct, addRecentSearch]);

  const quickTags = ['양파', '삼겹살', '계란', '휘발유', '사과', '우유'];

  return (
    <div>
      {/* 히어로 */}
      <section className={s.hero}>
        <div className={s.heroBg} />
        <div className={s.heroContent}>
          <h1 className={s.title}>이 가격,<br />진짜 싼 건가요?</h1>
          <p className={s.sub}>정부 공식 물가 + 마트 전단 데이터로<br/>지금 사도 될지 알려드립니다</p>

          <div className={s.search}>
            <div className={s.searchWrap}>
              <Search size={20} className={s.searchIcon} />
              <input
                ref={inputRef}
                className={s.searchInput}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setAcOpen(true); }}
                onFocus={() => setAcOpen(true)}
                placeholder="양파, 삼겹살, 계란..."
                autoComplete="off"
              />
              {query && <button className={s.searchClear} onClick={() => { setQuery(''); setAcOpen(false); }}><X size={16} /></button>}
            </div>
            {acOpen && matches.length > 0 && (
              <div className={s.acList}>
                {matches.map(p => (
                  <div key={p.id} className={s.acItem} onClick={() => selectProduct(p)}>
                    <span className={s.acIcon}>{p.icon}</span>
                    <div className={s.acInfo}>
                      <div className={s.acName}>{p.name}</div>
                      <div className={s.acCat}>{p.cat}</div>
                    </div>
                    <span className={s.acPrice}>{fmt(p.cur)}원</span>
                  </div>
                ))}
              </div>
            )}
            {acOpen && query.length === 0 && (
              <div className={s.trending}>
                {recentSearches.length > 0 && (
                  <>
                    <div className={s.trendTitleWrap}>
                      <span className={s.trendTitle}><Clock size={12} /> 최근 검색</span>
                      <button className={s.trendClear} onClick={clearRecentSearches}>지우기</button>
                    </div>
                    <div className={s.trendList}>
                      {recentSearches.slice(0, 5).map(rs => (
                        <button key={rs.timestamp} className={s.trendItem} onClick={() => {
                          const p = PRODUCTS.find(pr => pr.name === rs.query);
                          if (p) selectProduct(p);
                          else { setQuery(rs.query); setAcOpen(true); }
                        }}>
                          <Clock size={12} /> {rs.query}
                        </button>
                      ))}
                    </div>
                  </>
                )}
                <span className={s.trendTitle}>🔥 인기 검색어</span>
                <div className={s.trendList}>
                  {TRENDING.map((t, i) => (
                    <button key={t} className={s.trendItem} onClick={() => {
                      setQuery(t);
                      const p = PRODUCTS.find(pr => pr.name === t || t.includes(pr.name));
                      if (p) selectProduct(p);
                    }}>
                      <span className={s.trendRank}>{i+1}</span> {t}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className={s.tags}>
            {quickTags.map(t => (
              <button key={t} className={s.tag} onClick={() => {
                const p = PRODUCTS.find(pr => pr.name === t);
                if (p) selectProduct(p);
              }}>{t}</button>
            ))}
          </div>

          {/* 최근 검색 chips */}
          {recentSearches.length > 0 && (
            <div className={s.recentChips}>
              {recentSearches.slice(0, 6).map(rs => (
                <button key={rs.timestamp} className={s.recentChip} onClick={() => {
                  const p = PRODUCTS.find(pr => pr.name === rs.query);
                  if (p) selectProduct(p);
                  else { setQuery(rs.query); setAcOpen(true); }
                }}>
                  <Clock size={11} /> {rs.query}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* 관심 품목 */}
      {favorites.length > 0 && (
        <section className={s.sec}>
          <h2 className={s.secTitle}>⭐ 내 관심 품목</h2>
          <p className={s.secDesc}>관심 등록한 품목의 오늘 가격</p>
          <FavoritesDashboard />
        </section>
      )}

      {/* 오늘의 물가 */}
      <section className={s.sec}>
        <h2 className={s.secTitle}>오늘의 물가</h2>
        <p className={s.secDesc}>정부 공시 + 마트 평균 기준</p>
        <div className={s.priceGrid}>
          {PRODUCTS.slice(0, 8).map(p => {
            const diff = p.cur - p.avg;
            const pct = ((diff / p.avg) * 100).toFixed(1);
            let trend = 'same', icon = <Minus size={12} />;
            if (diff < -p.avg * 0.03) { trend = 'down'; icon = <TrendingDown size={12} />; }
            else if (diff > p.avg * 0.03) { trend = 'up'; icon = <TrendingUp size={12} />; }
            const fav = isFavorite(p.id);
            return (
              <div key={p.id} className={s.priceCard} onClick={() => selectProduct(p)}>
                <div className={s.priceCardTop}>
                  <span className={s.priceCardIcon}>{p.icon}</span>
                  <button
                    className={`${s.favBtn} ${fav ? s.favActive : ''}`}
                    onClick={(e) => { e.stopPropagation(); fav ? removeFavorite(p.id) : addFavorite(p.id); }}
                    title={fav ? '관심 해제' : '관심 등록'}
                  >
                    <Heart size={14} fill={fav ? 'currentColor' : 'none'} />
                  </button>
                </div>
                <div className={s.priceCardName}>{p.name} ({p.unit})</div>
                <div className={s.priceCardPrice}>{fmt(p.cur)}원</div>
                <span className={`${s.change} ${s[trend]}`}>{icon} {trend !== 'same' ? `${Math.abs(pct)}%` : '→'}</span>
              </div>
            );
          })}
        </div>
      </section>

      {/* 실시간 핫딜 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <h2 className={s.secTitle}>실시간 핫딜</h2>
          <button className={s.secMore} onClick={() => navigate('/hotdeal')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        <div className={s.dealGrid}>
          {HOTDEALS.slice(0, 4).map(d => (
            <div key={d.id} className={s.dealCard}>
              <div className={s.dealHead}>
                <span className={s.dealSource}>{d.source}</span>
                <span className={s.dealTime}>{d.time}</span>
              </div>
              <div className={s.dealTitle}>{d.title}</div>
              <div className={s.dealBottom}>
                <span className={s.dealPrice}>{d.price ? `${fmt(d.price)}원` : ''}</span>
                {d.price && d.origPrice && (
                  <span className={`${s.dealBadge} ${d.price / d.origPrice <= 0.5 ? s.ultra : d.price / d.origPrice <= 0.75 ? s.great : s.ok}`}>
                    {Math.round((1 - d.price / d.origPrice) * 100)}% 할인
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 이번 주 마트 BEST */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <h2 className={s.secTitle}>이번 주 마트 BEST</h2>
          <button className={s.secMore} onClick={() => navigate('/mart')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        <div className={s.martPreview}>
          {Object.entries(MART_DATA).map(([key, m]) => {
            const best = m.items.reduce((a, b) => b.disc > a.disc ? b : a);
            return (
              <div key={key} className={s.martCard} style={{ borderLeft: `3px solid ${m.color}` }}>
                <div className={s.martCardHead}>
                  <div className={s.martCardName}>{best.name}</div>
                  <div className={s.martShareWrap}>
                    <ShareButton
                      title={`${m.name} — ${best.name}`}
                      text={`[지갑지키미] ${m.name} ${best.name} ${fmt(best.sale)}원 (${best.disc}% 할인)`}
                      url={`${window.location.origin}/mart`}
                    />
                  </div>
                </div>
                <div className={s.martCardPrices}>
                  <span className={s.martCardSale}>{fmt(best.sale)}원</span>
                  <span className={s.martCardOrig}>{fmt(best.orig)}원</span>
                  <span className={s.martCardDisc}>-{best.disc}%</span>
                </div>
                <span className={s.martCardEvent}>{m.name} · {best.event}</span>
              </div>
            );
          })}
        </div>
      </section>

      {/* 집밥 비용 계산기 */}
      <RecipeCalculator />
    </div>
  );
}
