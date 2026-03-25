import { useState } from 'react';
import { Pencil } from 'lucide-react';
import { COMMUNITY_POSTS, PRODUCTS, fmt, verifyPrice } from '../data/mockData';
import useStore from '../stores/appStore';
import s from './CommunityPage.module.css';

const TABS = ['전체', '마트', '온라인', '외식', '기타'];
const VERIFY_STYLES = {
  great_deal: { bg:'rgba(52,211,153,.1)', color:'var(--green)', icon:'🔥' },
  verified:   { bg:'rgba(56,189,248,.08)', color:'var(--accent)', icon:'✅' },
  sus_low:    { bg:'rgba(248,113,113,.1)', color:'var(--red)', icon:'⚠️' },
  sus_high:   { bg:'rgba(248,113,113,.1)', color:'var(--red)', icon:'🚨' },
};

export default function CommunityPage() {
  const [filter, setFilter] = useState('전체');
  const [showWrite, setShowWrite] = useState(false);
  const [writeProduct, setWriteProduct] = useState('');
  const [writePrice, setWritePrice] = useState('');
  const { addToast } = useStore();

  const filtered = filter === '전체' ? COMMUNITY_POSTS : COMMUNITY_POSTS.filter(p => p.cat === filter);

  // 글쓰기 시 자동 검증
  const matchedProduct = PRODUCTS.find(p => writeProduct.includes(p.name));
  const verification = writePrice && matchedProduct
    ? verifyPrice(Number(writePrice), matchedProduct.avg)
    : null;

  const handleSubmit = () => {
    if (!verification?.canPost) {
      addToast('허위 가격이 의심되어 등록할 수 없습니다.', 'error');
      return;
    }
    addToast('게시글이 등록되었습니다! (데모)', 'success');
    setShowWrite(false);
    setWriteProduct(''); setWritePrice('');
  };

  return (
    <div>
      <div className={s.hdr}>
        <div><h2>핫딜 공유 커뮤니티</h2><p>직접 발견한 할인을 공유하고, 자동으로 시세 비교를 해드립니다</p></div>
        <button className={s.writeBtn} onClick={() => setShowWrite(!showWrite)}>
          <Pencil size={16} /> 글쓰기
        </button>
      </div>

      {/* 글쓰기 폼 — 자동 검증 */}
      {showWrite && (
        <div className={s.writeForm}>
          <h4>📝 핫딜 공유</h4>
          <div className={s.writeRow}>
            <input placeholder="품목명 (예: 삼겹살, 계란...)" value={writeProduct} onChange={e => setWriteProduct(e.target.value)} list="product-list" />
            <datalist id="product-list">{PRODUCTS.map(p => <option key={p.id} value={p.name} />)}</datalist>
            <input type="number" placeholder="가격 (원)" value={writePrice} onChange={e => setWritePrice(e.target.value)} />
          </div>
          {verification && (
            <div className={s.verifyResult} style={{ background: VERIFY_STYLES[verification.status]?.bg || 'var(--glass)', color: VERIFY_STYLES[verification.status]?.color || 'var(--text)' }}>
              <span>{verification.emoji}</span>
              <span>{verification.label}</span>
              {matchedProduct && <span className={s.verifyDetail}>DB 평균: {fmt(matchedProduct.avg)}원</span>}
            </div>
          )}
          {verification && !verification.canPost && (
            <div className={s.blocked}>⛔ 등록 차단됨 — 허위 가격이 의심됩니다.</div>
          )}
          <button className={s.submitBtn} onClick={handleSubmit} disabled={!verification?.canPost}>등록</button>
        </div>
      )}

      <div className={s.filterRow}>
        {TABS.map(t => (
          <button key={t} className={`${s.tab} ${filter === t ? s.tabActive : ''}`} onClick={() => setFilter(t)}>{t}</button>
        ))}
      </div>
      <div className={s.list}>
        {filtered.map(p => (
          <div key={p.id} className={s.post}>
            <span className={s.postCat}>{p.cat}</span>
            <div className={s.postBody}>
              <div className={s.postTitle}>
                {p.verified && <span className={s.verifyBadge} style={{ background: VERIFY_STYLES[p.verified]?.bg, color: VERIFY_STYLES[p.verified]?.color }}>
                  {VERIFY_STYLES[p.verified]?.icon}
                </span>}
                {p.title}
              </div>
              <div className={s.postMeta}>
                <span>{p.author}</span><span>{p.time}</span>
                <span>조회 {p.views}</span><span>댓글 {p.comments}</span>
              </div>
            </div>
            {p.priceVsAvg !== null && (
              <span className={`${s.priceBadge} ${p.priceVsAvg < -20 ? s.cheap : s.avgBadge}`}>
                평균 대비 {p.priceVsAvg}%
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
