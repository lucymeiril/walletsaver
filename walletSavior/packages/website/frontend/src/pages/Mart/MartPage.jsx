import { useState, useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { MART_DATA, PRODUCTS, MARTS, fmt } from '../../data/mockData';
import useStore from '../../stores/appStore';
import Modal from '../../components/common/Modal';
import s from './MartPage.module.css';

function getCategories(items) {
  const events = new Set(items.map(i => i.event));
  return ['전체', ...events];
}

function findCommonProducts(martData) {
  const productNames = {};
  for (const [martKey, mart] of Object.entries(martData)) {
    for (const item of mart.items) {
      const base = item.name.replace(/\s+\d+.*$/, '').replace(/\s+(1kg|100g|1L|5P|2입|24입|30구|12|21포|500g|1통|1포기|2마리|1망|793g|1.5kg|2.3L|600g).*$/i, '').trim();
      if (!productNames[base]) productNames[base] = {};
      productNames[base][martKey] = { ...item, mart: mart.name, color: mart.color || MARTS.find(m => m.key === martKey)?.color };
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

  const mart = MART_DATA[activeMart];
  const categories = useMemo(() => getCategories(mart.items), [mart]);
  const filteredItems = catFilter === '전체' ? mart.items : mart.items.filter(i => i.event === catFilter);
  const commonProducts = useMemo(() => findCommonProducts(MART_DATA), []);

  const flyerImages = MARTS.map(m => ({
    key: m.key,
    name: m.name,
    img: MART_DATA[m.key].flyerImg,
  }));

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

      <div className={s.info}>
        <span>행사 기간: {mart.period}</span>
        <span>총 {mart.items.length}개 상품</span>
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
          <div className={s.flyerViewer}>
            <img
              src={flyerImages[flyerIdx].img}
              alt={`${flyerImages[flyerIdx].name} 전단지`}
              className={`${s.flyerImg} ${flyerZoomed ? s.flyerImgZoomed : ''}`}
              onClick={() => setFlyerZoomed(!flyerZoomed)}
            />
            <button
              className={`${s.flyerNav} ${s.flyerPrev}`}
              onClick={() => setFlyerIdx(prev => (prev - 1 + flyerImages.length) % flyerImages.length)}
            >
              <ChevronLeft size={20} />
            </button>
            <button
              className={`${s.flyerNav} ${s.flyerNext}`}
              onClick={() => setFlyerIdx(prev => (prev + 1) % flyerImages.length)}
            >
              <ChevronRight size={20} />
            </button>
          </div>
          <div className={s.flyerDots}>
            {flyerImages.map((f, i) => (
              <button
                key={f.key}
                className={`${s.flyerDot} ${i === flyerIdx ? s.flyerDotActive : ''}`}
                onClick={() => setFlyerIdx(i)}
                title={f.name}
              />
            ))}
          </div>
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
            {filteredItems.map((item, i) => {
              const matched = PRODUCTS.find(p => item.name.includes(p.name));
              const diff = matched ? item.sale - matched.avg : null;
              return (
                <div key={i} className={s.card} onClick={() => setSaleDetail({ ...item, martName: mart.name, period: mart.period })}>
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
                  <div className={s.validity}>~ {mart.period.split('~')[1]?.trim() || mart.period}</div>
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
                      <div key={key} className={`${s.compareMart} ${item.sale === lowest ? s.compareLowest : ''}`}>
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
        const matched = PRODUCTS.find(p => saleDetail.name.includes(p.name));
        const diffVsAvg = matched ? saleDetail.sale - matched.avg : null;
        const periodParts = saleDetail.period?.split('~') || [];
        return (
          <Modal isOpen={!!saleDetail} onClose={() => setSaleDetail(null)} title={saleDetail.name} size="sm">
            <div className={s.detailBody}>
              <div className={s.detailImgWrap}>
                <img src={saleDetail.img} alt={saleDetail.name} className={s.detailImg} />
              </div>
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
                <span className={s.detailLabel}>행사 기간</span>
                <span>{periodParts[0]?.trim() || ''} ~ {periodParts[1]?.trim() || ''}</span>
              </div>
              <div className={s.detailRow}>
                <span className={s.detailLabel}>마트</span>
                <span>{saleDetail.martName}</span>
              </div>
              <div className={s.detailRow}>
                <span className={s.detailLabel}>행사 유형</span>
                <span className={s.detailEvent}>{saleDetail.event}</span>
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
