import { useState, useMemo, useEffect, useCallback, memo } from 'react';
import { X, Share2, ShoppingCart, Sparkles } from 'lucide-react';
import { MARTS } from '../../utils/constants';
import { fmt } from '../../utils/helpers';
import useStore from '../../stores/appStore';
import s from './ShoppingOptimizer.module.css';

function calcOptimalCombo(items, products) {
  const productMap = new Map(products.map(p => [p.id, p]));

  // 각 마트별 총합 계산
  const martTotals = MARTS.map(m => {
    const total = items.reduce((sum, item) => {
      const product = productMap.get(item.productId);
      if (!product || !product.stores) return sum;
      return sum + (product.stores[m.key] || 0) * item.quantity;
    }, 0);
    return { ...m, total };
  });

  // 최적 조합: 품목별로 가장 싼 마트 선택
  const optimalByMart = {};
  let optimalTotal = 0;

  items.forEach(item => {
    const product = productMap.get(item.productId);
    if (!product || !product.stores) return;

    let bestMart = MARTS[0];
    let bestPrice = product.stores[MARTS[0].key] || Infinity;
    MARTS.forEach(m => {
      const price = product.stores[m.key];
      if (price && price < bestPrice) {
        bestPrice = price;
        bestMart = m;
      }
    });

    const itemTotal = bestPrice * item.quantity;
    optimalTotal += itemTotal;

    if (!optimalByMart[bestMart.key]) {
      optimalByMart[bestMart.key] = { mart: bestMart, products: [], total: 0 };
    }
    optimalByMart[bestMart.key].products.push({ ...product, quantity: item.quantity, unitPrice: bestPrice });
    optimalByMart[bestMart.key].total += itemTotal;
  });

  const worstTotal = Math.max(...martTotals.map(m => m.total));
  const savings = worstTotal - optimalTotal;

  return { martTotals, optimalByMart: Object.values(optimalByMart), optimalTotal, worstTotal, savings };
}

const ShoppingOptimizer = memo(function ShoppingOptimizer() {
  const shoppingList = useStore((st) => st.shoppingList);
  const addToShoppingList = useStore((st) => st.addToShoppingList);
  const removeFromShoppingList = useStore((st) => st.removeFromShoppingList);
  const clearShoppingList = useStore((st) => st.clearShoppingList);
  const [searchQuery, setSearchQuery] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [dropOpen, setDropOpen] = useState(false);
  const [products, setProducts] = useState([]);

  // 상품 목록을 API에서 조회
  useEffect(() => {
    fetch('/api/products/search?per_page=50').then(r => r.json())
      .then(res => setProducts(res.data || []))
      .catch(console.error);
  }, []);

  const matches = useMemo(
    () => searchQuery.length > 0
      ? products.filter(p => p.name?.includes(searchQuery) || p.cat?.includes(searchQuery))
      : [],
    [searchQuery, products],
  );

  const handleAdd = useCallback((product) => {
    addToShoppingList(product.id, quantity);
    setSearchQuery('');
    setQuantity(1);
    setDropOpen(false);
  }, [addToShoppingList, quantity]);

  const listProducts = useMemo(
    () => shoppingList
      .map(item => {
        const product = products.find(p => p.id === item.productId);
        return product ? { ...item, product } : null;
      })
      .filter(Boolean),
    [shoppingList, products],
  );

  const result = useMemo(
    () => listProducts.length > 0 ? calcOptimalCombo(shoppingList, products) : null,
    [shoppingList, listProducts.length, products]
  );

  const handleShare = useCallback(() => {
    const text = listProducts.map(item =>
      `${item.product.icon} ${item.product.name} x${item.quantity}`
    ).join('\n');
    const summary = result
      ? `\n\n🛒 최적 조합 총합: ${fmt(result.optimalTotal)}원 (${fmt(result.savings)}원 절약!)`
      : '';
    const shareText = `📋 장보기 리스트\n${text}${summary}`;

    if (navigator.share) {
      navigator.share({ title: '장보기 리스트', text: shareText });
    } else {
      navigator.clipboard.writeText(shareText);
      alert('장보기 리스트가 복사되었습니다!');
    }
  }, [listProducts, result]);

  const cheapestKey = useMemo(
    () => result
      ? result.martTotals.reduce((a, b) => a.total < b.total ? a : b).key
      : null,
    [result],
  );

  return (
    <section className={s.sec}>
      <h2 className={s.title}>🛒 장보기 최적화</h2>
      <p className={s.sub}>이번 주 장 보러 어디 가야 제일 싸? — 품목 추가하고 최적 조합 확인</p>

      {/* 품목 추가 */}
      <div className={s.inputArea}>
        <div className={s.selectWrap}>
          <input
            className={s.selectInput}
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setDropOpen(true); }}
            onFocus={() => searchQuery && setDropOpen(true)}
            placeholder="품목 검색 (양파, 삼겹살...)"
            autoComplete="off"
          />
          {dropOpen && matches.length > 0 && (
            <div className={s.dropdown}>
              {matches.map(p => (
                <div key={p.id} className={s.dropItem} onClick={() => handleAdd(p)}>
                  <span className={s.dropIcon}>{p.icon}</span>
                  <span>{p.name} ({p.unit})</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <input
          className={s.qtyInput}
          type="number"
          min={1}
          max={99}
          value={quantity}
          onChange={(e) => setQuantity(Math.max(1, Number(e.target.value)))}
          placeholder="수량"
        />
        <button
          className={s.addBtn}
          disabled={matches.length === 0 && searchQuery.length > 0}
          onClick={() => matches.length > 0 && handleAdd(matches[0])}
        >
          <ShoppingCart size={16} /> 추가
        </button>
      </div>

      {/* 장보기 리스트 */}
      {listProducts.length > 0 && (
        <div className={s.listWrap}>
          {listProducts.map(item => (
            <div key={item.productId} className={s.listItem}>
              <span className={s.listItemIcon}>{item.product.icon}</span>
              <span>{item.product.name}</span>
              <span className={s.listItemQty}>x{item.quantity}</span>
              <span
                className={s.listItemRemove}
                onClick={() => removeFromShoppingList(item.productId)}
              >
                <X size={14} />
              </span>
            </div>
          ))}
          <button className={s.clearBtn} onClick={clearShoppingList}>전체 삭제</button>
        </div>
      )}

      {/* 결과 */}
      {result && (
        <div className={s.results}>
          {/* 마트별 총합 */}
          <div className={s.martGrid}>
            {result.martTotals.map(m => (
              <div key={m.key} className={`${s.martTotal} ${m.key === cheapestKey ? s.cheapest : ''}`}>
                <div className={s.martTotalHead}>
                  <span className={s.martDot} style={{ background: m.color }} />
                  <span className={s.martName}>{m.name}</span>
                  {m.key === cheapestKey && <span className={s.cheapestBadge}>최저!</span>}
                </div>
                <div className={s.martTotalPrice}>{fmt(m.total)}원</div>
              </div>
            ))}
          </div>

          {/* 최적 조합 */}
          <div className={s.optimal}>
            <div className={s.optimalGlow} />
            <div className={s.optimalTitle}>
              <Sparkles size={18} /> 최적 조합
            </div>
            <div className={s.optimalList}>
              {result.optimalByMart.map(group => (
                <div key={group.mart.key} className={s.optimalItem}>
                  <div className={s.optimalItemLeft}>
                    <span className={s.martDot} style={{ background: group.mart.color }} />
                    <span>{group.mart.name}</span>
                    <span className={s.optimalItemProducts}>
                      {group.products.map(p => p.name).join(' + ')}
                    </span>
                  </div>
                  <span className={s.optimalItemPrice}>{fmt(group.total)}원</span>
                </div>
              ))}
            </div>
            <div className={s.optimalTotal}>
              <span className={s.optimalTotalLabel}>최적 조합 총합</span>
              <span className={s.optimalTotalPrice}>{fmt(result.optimalTotal)}원</span>
            </div>
          </div>

          {/* 절약 */}
          {result.savings > 0 && (
            <div className={s.savings}>
              <span className={s.savingsIcon}>💰</span>
              <div className={s.savingsText}>
                <strong>최대 {fmt(result.savings)}원 절약!</strong>
                <span>전부 비싼 곳에서 사는 것 대비</span>
              </div>
            </div>
          )}

          {/* 공유 */}
          <button className={s.shareBtn} onClick={handleShare}>
            <Share2 size={16} /> 장보기 리스트 공유
          </button>
        </div>
      )}

      {listProducts.length === 0 && (
        <div className={s.empty}>
          장볼 품목을 추가해보세요! 🛒<br />마트별 가격 비교와 최적 조합을 알려드려요
        </div>
      )}
    </section>
  );
});

export default ShoppingOptimizer;
