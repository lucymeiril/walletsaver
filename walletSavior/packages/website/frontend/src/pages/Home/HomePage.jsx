import { useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X, TrendingUp, TrendingDown, Minus, ArrowRight, Heart, Clock, Fuel } from 'lucide-react';
import { MARTS, GAS_STATIONS, fmt } from '../../data/mockData';
import { HOTDEALS, MART_DATA, COMMUNITY_POSTS, products as PRODUCTS, TRENDING } from '../../data/seedData';
import useStore from '../../stores/appStore';
import s from './HomePage.module.css';

const CATEGORIES = [
  { icon: '🥩', name: '농축산물', path: '/price' },
  { icon: '🏪', name: '마트',     path: '/mart' },
  { icon: '⛽', name: '주유소',   path: '/local' },
  { icon: '🍽️', name: '식당',     path: '/local' },
  { icon: '👗', name: '의류',     path: '/hotdeal' },
  { icon: '🛵', name: '배달',     path: '/community' },
];

export default function HomePage() {
  const navigate = useNavigate();
  const {
    setSelectedProduct,
    favorites, addFavorite, removeFavorite, isFavorite,
    recentSearches, addRecentSearch, clearRecentSearches,
    addToShoppingList, addToast,
  } = useStore();

  const [query, setQuery] = useState('');
  const [acOpen, setAcOpen] = useState(false);
  const [martTab, setMartTab] = useState('emart');
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

  const activeMart = MART_DATA[martTab];
  const topGas = [...GAS_STATIONS].sort((a, b) => a.gasoline - b.gasoline).slice(0, 4);

  return (
    <div>
      {/* 히어로 */}
      <section className={s.hero}>
        <div className={s.heroBg} />
        <div className={s.heroContent}>
          <h1 className={s.title}>이 가격,<br />진짜 싼 건가요?</h1>
          <p className={s.sub}>정부 공식 물가 + 마트 전단 데이터로<br />지금 사도 될지 알려드립니다</p>

          <div className={s.search}>
            <div className={s.searchWrap}>
              <Search size={20} className={s.searchIcon} />
              <input
                ref={inputRef}
                className={s.searchInput}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setAcOpen(true); }}
                onFocus={() => setAcOpen(true)}
                placeholder="무엇을 찾으시나요?"
                autoComplete="off"
              />
              {query && (
                <button className={s.searchClear} onClick={() => { setQuery(''); setAcOpen(false); }}>
                  <X size={16} />
                </button>
              )}
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
                      <span className={s.trendRank}>{i + 1}</span> {t}
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

      {/* 카테고리 퀵 링크 */}
      <section className={s.sec}>
        <h2 className={s.secTitle}>카테고리</h2>
        <p className={s.secDesc}>원하는 정보에 3클릭 이내로 접근하세요</p>
        <div className={s.catGrid}>
          {CATEGORIES.map(cat => (
            <button key={cat.name} className={s.catLink} onClick={() => navigate(cat.path)}>
              <span className={s.catIcon}>{cat.icon}</span>
              <span className={s.catName}>{cat.name}</span>
            </button>
          ))}
        </div>
      </section>

      {/* 오늘의 핫딜 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>🔥 오늘의 핫딜</h2>
            <p className={s.secDesc}>실시간 커뮤니티 핫딜 모아보기</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/hotdeal')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        <div className={s.dealGrid}>
          {HOTDEALS.slice(0, 4).map(d => {
            const ratio = d.price && d.origPrice ? d.price / d.origPrice : null;
            let tierClass = '';
            if (ratio !== null) {
              if (ratio <= 0.5) tierClass = s.ultra;
              else if (ratio <= 0.65) tierClass = s.great;
              else if (ratio <= 0.8) tierClass = s.good;
              else tierClass = s.ok;
            }
            return (
              <div key={d.id} className={s.dealCard} onClick={() => navigate('/hotdeal', { state: { openDealId: d.id } })}>
                <div className={s.dealHead}>
                  <span className={s.dealSource}>{d.source}</span>
                  <span className={s.dealTime}>{d.time}</span>
                </div>
                <div className={s.dealTitle}>{d.title}</div>
                <div className={s.dealBottom}>
                  <span className={s.dealPrice}>{d.price ? `${fmt(d.price)}원` : ''}</span>
                  {ratio !== null && (
                    <span className={`${s.dealBadge} ${tierClass}`}>
                      {Math.round((1 - ratio) * 100)}% 할인
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

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
                  <div className={s.priceCardBtns}>
                    <button
                      className={s.cartSmall}
                      onClick={(e) => {
                        e.stopPropagation();
                        addToShoppingList({ productId: p.id, name: p.name, price: p.cur, unit: p.unit, icon: p.icon });
                        addToast(`${p.name}을(를) 장보기 리스트에 추가했어요`, 'success');
                      }}
                      title="장보기에 추가"
                    >
                      🛒
                    </button>
                    <button
                      className={`${s.favBtn} ${fav ? s.favActive : ''}`}
                      onClick={(e) => { e.stopPropagation(); fav ? removeFavorite(p.id) : addFavorite(p.id); }}
                      title={fav ? '관심 해제' : '관심 등록'}
                    >
                      <Heart size={14} fill={fav ? 'currentColor' : 'none'} />
                    </button>
                  </div>
                </div>
                <div className={s.priceCardName}>{p.name} ({p.unit})</div>
                <div className={s.priceCardPrice}>{fmt(p.cur)}원</div>
                <span className={`${s.change} ${s[trend]}`}>{icon} {trend !== 'same' ? `${Math.abs(pct)}%` : '→'}</span>
              </div>
            );
          })}
        </div>
      </section>

      {/* 마트 세일 미리보기 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>🏪 이번 주 마트 세일</h2>
            <p className={s.secDesc}>이마트 · 홈플러스 · 롯데마트 · 코스트코</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/mart')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        <div className={s.martTabs}>
          {MARTS.map(m => (
            <button
              key={m.key}
              className={`${s.martTab} ${martTab === m.key ? s.martTabActive : ''}`}
              onClick={() => setMartTab(m.key)}
            >
              <span className={s.martDot} style={{ background: m.color }} />
              {m.name}
            </button>
          ))}
        </div>
        <div className={s.martSaleGrid}>
          {activeMart.items.slice(0, 4).map((item, i) => (
            <div key={i} className={s.martSaleCard} onClick={() => navigate('/mart')}>
              <div className={s.martSaleName}>{item.name}</div>
              <div className={s.martSalePrices}>
                <span className={s.martSalePrice}>{fmt(item.sale)}원</span>
                <span className={s.martSaleOrig}>{fmt(item.orig)}원</span>
                <span className={s.martSaleDisc}>-{item.disc}%</span>
              </div>
              <div className={s.martSaleBottom}>
                <span className={s.martSaleEvent}>{activeMart.name} · {item.event}</span>
                <button
                  className={s.cartSmall}
                  onClick={(e) => {
                    e.stopPropagation();
                    addToShoppingList({ name: item.name, price: item.sale, icon: '🏪' });
                    addToast(`${item.name}을(를) 장보기 리스트에 추가했어요`, 'success');
                  }}
                  title="장보기에 추가"
                >
                  🛒
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 주변 최저가 주유소 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>⛽ 주변 최저가 주유소</h2>
            <p className={s.secDesc}>현재 위치 기준 가까운 주유소</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/local')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        <div className={s.gasGrid}>
          {topGas.map((g, i) => (
            <div key={i} className={s.gasCard}>
              <span className={s.gasRank}>{i + 1}</span>
              <div className={s.gasInfo}>
                <div className={s.gasName}>{g.name}</div>
                <div className={s.gasAddr}>{g.addr}</div>
              </div>
              <span className={s.gasPrice}>{fmt(g.gasoline)}원</span>
            </div>
          ))}
        </div>
      </section>

      {/* 커뮤니티 인기글 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>💬 커뮤니티 인기 게시글</h2>
            <p className={s.secDesc}>직접 발견한 할인을 공유하세요</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/community')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        <div className={s.communityList}>
          {COMMUNITY_POSTS.slice(0, 5).map(p => (
            <div key={p.id} className={s.communityItem} onClick={() => navigate('/community', { state: { openPostId: p.id } })}>
              <span className={s.comCat}>{p.cat}</span>
              <div className={s.comBody}>
                <div className={s.comTitle}>{p.title}</div>
                <div className={s.comMeta}>
                  <span>{p.author}</span>
                  <span>{p.time}</span>
                  <span>👁️ {p.views}</span>
                  <span>💬 {p.commentData?.length || p.comments}</span>
                </div>
              </div>
              {p.priceVsAvg !== null && (
                <span className={`${s.comBadge} ${p.priceVsAvg < -20 ? s.cheap : ''}`}>
                  평균 대비 {p.priceVsAvg}%
                </span>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
