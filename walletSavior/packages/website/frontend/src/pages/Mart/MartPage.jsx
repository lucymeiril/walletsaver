import { useState, useMemo, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight, ExternalLink, RefreshCw } from 'lucide-react';
import { MARTS, fmt } from '../../data/mockData';
import useStore from '../../stores/appStore';
import Modal from '../../components/common/Modal';
import Spinner from '../../components/common/Spinner';
import s from './MartPage.module.css';

function getCategories(items) {
  const events = new Set(items.map(i => i.event));
  return ['전체', ...events];
}

function findCommonProducts(martDeals) {
  const productNames = {};
  for (const [martKey, items] of Object.entries(martDeals)) {
    const martInfo = MARTS.find(m => m.key === martKey);
    for (const item of (items || [])) {
      const base = item.name.replace(/\s+\d+.*$/, '').replace(/\s+(1kg|100g|1L|5P|2입|24입|30구|12|21포|500g|1통|1포기|2마리|1망|793g|1.5kg|2.3L|600g).*$/i, '').trim();
      if (!productNames[base]) productNames[base] = {};
      productNames[base][martKey] = { ...item, mart: martInfo?.name, color: martInfo?.color };
    }
  }
  return Object.entries(productNames)
    .filter(([, marts]) => Object.keys(marts).length >= 2)
    .map(([name, marts]) => ({ name, marts }));
}

export default function MartPage() {
  const [activeMart, setActiveMart] = useState('emart');
  const [mode, setMode] = useState('sale');
  const [catFilter, setCatFilter] = useState('전체');
  const [flyerIdx, setFlyerIdx] = useState(0);
  const [flyerZoomed, setFlyerZoomed] = useState(false);
  const [saleDetail, setSaleDetail] = useState(null);

  const { addToShoppingList, addToast } = useStore();

  const [martDeals, setMartDeals] = useState({});
  const [martMeta, setMartMeta] = useState({});
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);

  // Flyer state
  const [flyerData, setFlyerData] = useState({});
  const [flyerLoading, setFlyerLoading] = useState(false);
  const [flyerError, setFlyerError] = useState(null);
  const [flyerMart, setFlyerMart] = useState('emart');

  // Fetch all mart deals on mount (needed for compare view)
  useEffect(() => {
    const martKeys = MARTS.map(m => m.key);
    Promise.all(
      martKeys.map(key =>
        fetch(`/api/marts/${key}/promotions`).then(r => r.json())
          .then(res => ({
            key,
            lastCrawledAt: res.data?.last_crawled_at || '',
            items: (Array.isArray(res.data) ? res.data : res.data?.items || []).map(d => ({
              name: d.name,
              sale: d.price ?? d.sale,
              orig: d.original_price ?? d.orig,
              disc: d.discount_rate ?? d.disc,
              event: d.event_name ?? (d.event || '할인'),
              img: d.image_url ?? d.img ?? '',
              detailUrl: d.source_url ?? d.detail_url ?? '',
              unit: d.unit ?? '',
              store: d.store ?? '',
              crawledAt: d.crawled_at ?? '',
            })),
          }))
      )
    ).then(results => {
      const deals = {};
      const meta = {};
      results.forEach(r => {
        deals[r.key] = r.items;
        meta[r.key] = { lastCrawledAt: r.lastCrawledAt };
      });
      setMartDeals(deals);
      setMartMeta(meta);
    }).catch(err => {
      console.error(err);
      addToast('마트 데이터를 불러오는데 실패했습니다', 'error');
    }).finally(() => setLoading(false));

    fetch('/api/products/search?per_page=50').then(r => r.json())
      .then(res => setProducts(res.data || []))
      .catch(console.error);
  }, []);

  // Fetch flyer data when entering flyer mode or switching mart
  const fetchFlyerData = useCallback((store) => {
    if (flyerData[store]) return; // already loaded
    setFlyerLoading(true);
    setFlyerError(null);
    fetch(`/api/marts/${store}/flyers`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(res => {
        setFlyerData(prev => ({ ...prev, [store]: res.data }));
      })
      .catch(err => {
        console.error('Flyer fetch error:', err);
        setFlyerError(`${store} 전단지를 불러올 수 없습니다`);
      })
      .finally(() => setFlyerLoading(false));
  }, [flyerData]);

  useEffect(() => {
    if (mode === 'flyer') {
      fetchFlyerData(flyerMart);
      // Preload other marts' flyer data for quick links
      MARTS.forEach(m => {
        if (m.key !== flyerMart && !flyerData[m.key]) {
          fetch(`/api/marts/${m.key}/flyers`)
            .then(r => r.ok ? r.json() : null)
            .then(res => {
              if (res?.data) setFlyerData(prev => ({ ...prev, [m.key]: res.data }));
            })
            .catch(() => {});
        }
      });
    }
  }, [mode, flyerMart, fetchFlyerData]);

  const martInfo = MARTS.find(m => m.key === activeMart);
  const martItems = martDeals[activeMart] || [];
  const categories = useMemo(() => getCategories(martItems), [martItems]);
  const filteredItems = catFilter === '전체' ? martItems : martItems.filter(i => i.event === catFilter);
  const commonProducts = useMemo(() => findCommonProducts(martDeals), [martDeals]);

  // Generate period from current week
  const now = new Date();
  const startOfWeek = new Date(now); startOfWeek.setDate(now.getDate() - now.getDay());
  const endOfWeek = new Date(startOfWeek); endOfWeek.setDate(startOfWeek.getDate() + 6);
  const martPeriod = `${startOfWeek.getMonth()+1}/${startOfWeek.getDate()} ~ ${endOfWeek.getMonth()+1}/${endOfWeek.getDate()}`;

  const currentFlyer = flyerData[flyerMart];
  const flyerPages = currentFlyer?.flyer_pages || [];
  const flyerHasImages = flyerPages.length > 0;

  return (
    <div>
      <div className={s.hdr}>
        <h2>마트 할인 전단</h2>
        <p>이마트 · 홈플러스 · 롯데마트 · 코스트코 이번 주 할인</p>
      </div>

      {/* Mart Tabs */}
      <div className={s.tabs}>
        {MARTS.map(m => (
          <button
            key={m.key}
            className={`${s.tab} ${activeMart === m.key ? s.tabActive : ''}`}
            onClick={() => { setActiveMart(m.key); setCatFilter('전체'); }}
          >
            <span className={s.dot} style={{ background: m.color }} />{m.name}
          </button>
        ))}
      </div>

      {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem 0' }}><Spinner /></div>}

      <div className={s.info}>
        <span>행사 기간: {martPeriod}</span>
        <span>총 {martItems.length}개 상품</span>
        {martMeta[activeMart]?.lastCrawledAt && (
          <span className={s.crawlBadge} title="크롤링된 실제 데이터">
            🔄 {(() => {
              const d = new Date(martMeta[activeMart].lastCrawledAt);
              return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')} 수집`;
            })()}
          </span>
        )}
      </div>

      {/* Mode Toggle */}
      <div className={s.modeRow}>
        <button className={`${s.modeBtn} ${mode === 'sale' ? s.modeBtnActive : ''}`} onClick={() => setMode('sale')}>
          📋 세일 상품
        </button>
        <button className={`${s.modeBtn} ${mode === 'flyer' ? s.modeBtnActive : ''}`} onClick={() => setMode('flyer')}>
          📰 전단지 보기
        </button>
        <button className={`${s.modeBtn} ${mode === 'compare' ? s.modeBtnActive : ''}`} onClick={() => setMode('compare')}>
          ⚖️ 마트별 비교
        </button>
      </div>

      {/* Flyer Viewer */}
      {mode === 'flyer' && (
        <div className={s.flyerSection}>
          {/* Mart selector for flyer */}
          <div className={s.flyerMartTabs}>
            {MARTS.map(m => (
              <button
                key={m.key}
                className={`${s.flyerMartTab} ${flyerMart === m.key ? s.flyerMartTabActive : ''}`}
                style={flyerMart === m.key ? { borderColor: m.color, color: m.color } : {}}
                onClick={() => { setFlyerMart(m.key); setFlyerIdx(0); setFlyerZoomed(false); }}
              >
                <span className={s.dot} style={{ background: m.color }} />{m.name}
              </button>
            ))}
          </div>

          {/* Flyer period info */}
          {currentFlyer && (
            <div className={s.flyerPeriod}>
              <span>📅 행사 기간: {currentFlyer.display_period}</span>
              <a
                href={currentFlyer.web_url}
                target="_blank"
                rel="noopener noreferrer"
                className={s.flyerWebLink}
              >
                원본 사이트에서 보기 <ExternalLink size={14} />
              </a>
            </div>
          )}

          {/* Loading state */}
          {flyerLoading && (
            <div className={s.flyerLoading}>
              <Spinner />
              <span>전단지를 불러오는 중...</span>
            </div>
          )}

          {/* Error state */}
          {flyerError && !flyerLoading && (
            <div className={s.flyerError}>
              <p>⚠️ {flyerError}</p>
              <button
                className={s.flyerRetryBtn}
                onClick={() => {
                  setFlyerData(prev => { const next = { ...prev }; delete next[flyerMart]; return next; });
                  fetchFlyerData(flyerMart);
                }}
              >
                <RefreshCw size={14} /> 다시 시도
              </button>
            </div>
          )}

          {/* Flyer content: images carousel if available */}
          {!flyerLoading && !flyerError && flyerHasImages && (
            <>
              <div className={s.flyerViewer}>
                <img
                  src={flyerPages[flyerIdx]?.image_url}
                  alt={`${currentFlyer.name} 전단지 ${flyerIdx + 1}페이지`}
                  className={`${s.flyerImg} ${flyerZoomed ? s.flyerImgZoomed : ''}`}
                  onClick={() => setFlyerZoomed(!flyerZoomed)}
                />
                {flyerPages.length > 1 && (
                  <>
                    <button
                      className={`${s.flyerNav} ${s.flyerPrev}`}
                      onClick={() => setFlyerIdx(prev => (prev - 1 + flyerPages.length) % flyerPages.length)}
                    >
                      <ChevronLeft size={20} />
                    </button>
                    <button
                      className={`${s.flyerNav} ${s.flyerNext}`}
                      onClick={() => setFlyerIdx(prev => (prev + 1) % flyerPages.length)}
                    >
                      <ChevronRight size={20} />
                    </button>
                  </>
                )}
                <div className={s.flyerPageBadge}>
                  {flyerIdx + 1} / {flyerPages.length}
                </div>
              </div>
              {flyerPages.length > 1 && (
                <div className={s.flyerDots}>
                  {flyerPages.map((_, i) => (
                    <button
                      key={i}
                      className={`${s.flyerDot} ${i === flyerIdx ? s.flyerDotActive : ''}`}
                      onClick={() => setFlyerIdx(i)}
                      title={`${i + 1}페이지`}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          {/* No images: show link card to view flyer on mart's website */}
          {!flyerLoading && !flyerError && currentFlyer && !flyerHasImages && (
            <div className={s.flyerLinkCard}>
              <div className={s.flyerLinkIcon}>📰</div>
              <h3 className={s.flyerLinkTitle}>{currentFlyer.name} 전단지</h3>
              <p className={s.flyerLinkDesc}>{currentFlyer.description}</p>
              {currentFlyer.display_period && (
                <p className={s.flyerLinkPeriod}>📅 {currentFlyer.display_period}</p>
              )}
              <a
                href={currentFlyer.web_url}
                target="_blank"
                rel="noopener noreferrer"
                className={s.flyerLinkBtn}
              >
                전단지 보러가기 <ExternalLink size={16} />
              </a>
              <p className={s.flyerLinkNote}>
                {currentFlyer.name} 공식 사이트에서 최신 전단지를 확인하세요
              </p>
            </div>
          )}

          {/* All marts quick links */}
          {!flyerLoading && (
            <div className={s.flyerQuickLinks}>
              <h4 className={s.flyerQuickTitle}>🔗 마트별 전단지 바로가기</h4>
              <div className={s.flyerQuickGrid}>
                {MARTS.map(m => {
                  const data = flyerData[m.key];
                  const webUrl = data?.web_url;
                  if (!webUrl) return null;
                  return (
                    <a
                      key={m.key}
                      href={webUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={s.flyerQuickItem}
                    >
                      <span className={s.dot} style={{ background: m.color }} />
                      <span>{m.name}</span>
                      <ExternalLink size={12} />
                    </a>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Sale Grid */}
      {mode === 'sale' && (
        <>
          <div className={s.catRow}>
            <span className={s.catLabel}>카테고리:</span>
            {categories.map(c => (
              <button
                key={c}
                className={`${s.catBtn} ${catFilter === c ? s.catBtnActive : ''}`}
                onClick={() => setCatFilter(c)}
              >
                {c}
              </button>
            ))}
          </div>

          <div className={s.grid}>
            {filteredItems.length === 0 && !loading && (
              <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '3rem 1rem', color: 'var(--text3)' }}>
                <p style={{ fontSize: '1.2rem', marginBottom: '0.5rem' }}>📭 데이터가 없습니다</p>
                <p style={{ fontSize: '0.85rem' }}>
                  크롤러에서 수집 → 크롤러 관리자 승인 → DB 관리자 승인 후 표시됩니다.
                </p>
              </div>
            )}
            {filteredItems.map((item, i) => {
              const matched = products.find(p => item.name?.includes(p.name));
              const diff = matched ? item.sale - matched.avg : null;
              return (
                <div key={i} className={s.card} onClick={() => setSaleDetail({ ...item, martName: martInfo?.name, period: martPeriod })}>
                  <div className={s.cardName}>{item.name}</div>
                  <div className={s.cardPrices}>
                    <span className={s.sale}>{fmt(item.sale)}원</span>
                    <span className={s.orig}>{fmt(item.orig)}원</span>
                    <span className={s.disc}>-{item.disc}%</span>
                  </div>
                  {diff !== null && (
                    <div className={s.vs}>
                      시세 평균 대비 <em className={diff <= 0 ? s.cheap : s.expensive}>{diff <= 0 ? fmt(diff) : `+${fmt(diff)}`}원</em>
                    </div>
                  )}
                  <div className={s.cardBottom}>
                    <span className={s.event}>{item.event}</span>
                    <button
                      className={s.cartMini}
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
                  <div className={s.validity}>~ {martPeriod.split('~')[1]?.trim() || martPeriod}</div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Compare View */}
      {mode === 'compare' && (
        <div className={s.compareSection}>
          <h3 className={s.compareTitle}>⚖️ 같은 상품 마트별 가격 비교</h3>
          <div className={s.compareGrid}>
            {commonProducts.map(({ name, marts: martPrices }) => {
              const prices = Object.values(martPrices).map(m => m.sale);
              const lowest = Math.min(...prices);
              return (
                <div key={name} className={s.compareRow}>
                  <div className={s.compareProductName}>{name}</div>
                  <div className={s.comparePrices}>
                    {Object.entries(martPrices).map(([key, item]) => (
                      <div
                        key={key}
                        className={`${s.compareMart} ${item.sale === lowest ? s.compareLowest : ''} ${s.compareMartClickable}`}
                        onClick={() => {
                          const mInfo = MARTS.find(m => m.key === key);
                          setSaleDetail({ ...item, martName: mInfo?.name || item.mart, period: martPeriod });
                        }}
                      >
                        <span className={s.compareMartName}>
                          <span className={s.compareMartDot} style={{ background: item.color }} />
                          {item.mart}
                        </span>
                        <span className={s.compareMartPrice}>
                          {fmt(item.sale)}원
                          {item.sale === lowest && ' 🏆'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
            {commonProducts.length === 0 && (
              <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)' }}>
                비교 가능한 동일 상품이 없습니다.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Sale Detail Modal */}
      {saleDetail && (() => {
        const matched = products.find(p => saleDetail.name?.includes(p.name));
        const diffVsAvg = matched ? saleDetail.sale - matched.avg : null;
        const periodParts = saleDetail.period?.split('~') || [];
        return (
          <Modal isOpen={!!saleDetail} onClose={() => setSaleDetail(null)} title={saleDetail.name} size="sm">
            <div className={s.detailBody}>
              {saleDetail.img && (
                <div className={s.detailImgWrap}>
                  <img src={saleDetail.img} alt={saleDetail.name} className={s.detailImg} />
                  {saleDetail.disc > 0 && (
                    <span className={s.detailDiscBadge}>-{saleDetail.disc}%</span>
                  )}
                </div>
              )}
              <div className={s.detailRow}>
                <span className={s.detailLabel}>판매가</span>
                <span className={s.detailSale}>{fmt(saleDetail.sale)}원</span>
              </div>
              <div className={s.detailRow}>
                <span className={s.detailLabel}>정가</span>
                <span className={s.detailOrig}>{fmt(saleDetail.orig)}원</span>
              </div>
              <div className={s.detailRow}>
                <span className={s.detailLabel}>할인율</span>
                <span className={s.detailDisc}>-{saleDetail.disc}%</span>
              </div>
              <div className={s.detailRow}>
                <span className={s.detailLabel}>행사 유형</span>
                <span className={s.detailEvent}>{saleDetail.event}</span>
              </div>
              {saleDetail.unit && (
                <div className={s.detailRow}>
                  <span className={s.detailLabel}>규격/단위</span>
                  <span>{saleDetail.unit}</span>
                </div>
              )}
              {saleDetail.store && (
                <div className={s.detailRow}>
                  <span className={s.detailLabel}>판매 매장</span>
                  <span>{saleDetail.store}</span>
                </div>
              )}
              <div className={s.detailRow}>
                <span className={s.detailLabel}>마트</span>
                <span>{saleDetail.martName}</span>
              </div>
              <div className={s.detailRow}>
                <span className={s.detailLabel}>행사 기간</span>
                <span>{periodParts[0]?.trim() || ''} ~ {periodParts[1]?.trim() || ''}</span>
              </div>
              {diffVsAvg !== null && (
                <div className={s.detailRow}>
                  <span className={s.detailLabel}>시세 평균 대비</span>
                  <span className={diffVsAvg <= 0 ? s.cheap : s.expensive}>
                    {diffVsAvg <= 0 ? fmt(diffVsAvg) : `+${fmt(diffVsAvg)}`}원
                  </span>
                </div>
              )}
              <div className={s.detailActions}>
                {saleDetail.detailUrl && (
                  <a
                    href={saleDetail.detailUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={s.detailLinkBtn}
                  >
                    <ExternalLink size={16} />
                    상품 페이지로 이동
                  </a>
                )}
                <button
                  className={s.detailCartBtn}
                  onClick={() => {
                    addToShoppingList({ name: saleDetail.name, price: saleDetail.sale, icon: '🏪' });
                    addToast(`${saleDetail.name}을(를) 장보기 리스트에 추가했어요`, 'success');
                    setSaleDetail(null);
                  }}
                >
                  🛒 장보기에 추가
                </button>
                <button className={s.detailCloseBtn} onClick={() => setSaleDetail(null)}>
                  닫기
                </button>
              </div>
            </div>
          </Modal>
        );
      })()}
    </div>
  );
}
