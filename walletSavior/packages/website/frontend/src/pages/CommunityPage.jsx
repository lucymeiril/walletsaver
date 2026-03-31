import { useState, useRef } from 'react';
import { Pencil, ImagePlus, X } from 'lucide-react';
import { COMMUNITY_POSTS, PRODUCTS, fmt, verifyPrice } from '../data/mockData';
import useStore from '../stores/appStore';
import DetailModal from '../components/modals/DetailModal';
import s from './CommunityPage.module.css';

const TABS = ['전체', '마트', '온라인', '외식', '기타'];
const CATS = ['마트', '온라인', '외식', '기타'];
const VERIFY_STYLES = {
  great_deal: { bg:'rgba(52,211,153,.1)', color:'var(--green)', icon:'🔥' },
  verified:   { bg:'rgba(56,189,248,.08)', color:'var(--accent)', icon:'✅' },
  sus_low:    { bg:'rgba(248,113,113,.1)', color:'var(--red)', icon:'⚠️' },
  sus_high:   { bg:'rgba(248,113,113,.1)', color:'var(--red)', icon:'🚨' },
};

export default function CommunityPage() {
  const [filter, setFilter] = useState('전체');
  const [showWrite, setShowWrite] = useState(false);
  const [detail, setDetail] = useState(null);
  const { isLoggedIn, addToast, login } = useStore();

  // 글쓰기 폼
  const [wTitle, setWTitle] = useState('');
  const [wBody, setWBody] = useState('');
  const [wCat, setWCat] = useState('마트');
  const [wProduct, setWProduct] = useState('');
  const [wPrice, setWPrice] = useState('');
  const [wImages, setWImages] = useState([]);
  const fileRef = useRef(null);

  const filtered = filter === '전체' ? COMMUNITY_POSTS : COMMUNITY_POSTS.filter(p => p.cat === filter);

  // 자동 검증
  const matchedProduct = PRODUCTS.find(p => wProduct.includes(p.name));
  const verification = wPrice && matchedProduct ? verifyPrice(Number(wPrice), matchedProduct.avg) : null;

  // 이미지 미리보기
  const handleImageAdd = (e) => {
    const files = Array.from(e.target.files);
    files.forEach(f => {
      const reader = new FileReader();
      reader.onload = (ev) => setWImages(prev => [...prev, ev.target.result]);
      reader.readAsDataURL(f);
    });
  };

  const handleWrite = () => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다.', 'error');
      return;
    }
    if (!wTitle.trim()) { addToast('제목을 입력해주세요.', 'error'); return; }
    if (verification && !verification.canPost) { addToast('허위 가격이 의심되어 등록할 수 없습니다.', 'error'); return; }
    addToast('게시글이 등록되었습니다! (데모)', 'success');
    setShowWrite(false);
    setWTitle(''); setWBody(''); setWProduct(''); setWPrice(''); setWImages([]);
  };

  const handleWriteBtn = () => {
    if (!isLoggedIn) {
      // 데모용: 자동 로그인
      login({ name: '데모유저', email: 'demo@wallet.com' });
      addToast('데모 로그인 완료! 이제 글을 작성할 수 있습니다.', 'success');
    }
    setShowWrite(!showWrite);
  };

  return (
    <div>
      <div className={s.hdr}>
        <div><h2>핫딜 공유 커뮤니티</h2><p>직접 발견한 할인을 공유하고, 자동으로 시세 비교를 해드립니다</p></div>
        <button className={s.writeBtn} onClick={handleWriteBtn}>
          <Pencil size={16} /> {isLoggedIn ? '글쓰기' : '로그인 후 글쓰기'}
        </button>
      </div>

      {/* 풀 스펙 글쓰기 폼 */}
      {showWrite && (
        <div className={s.writeForm}>
          <div className={s.writeHeader}><h4>📝 핫딜 공유</h4><button className={s.closeWrite} onClick={() => setShowWrite(false)}><X size={16} /></button></div>

          <input className={s.titleInput} placeholder="제목을 입력하세요" value={wTitle} onChange={e => setWTitle(e.target.value)} />

          <textarea className={s.bodyInput} placeholder="내용을 입력하세요 (가격, 매장 위치, 수량 제한 등)" rows={4} value={wBody} onChange={e => setWBody(e.target.value)} />

          <div className={s.writeRow}>
            <select value={wCat} onChange={e => setWCat(e.target.value)}>
              {CATS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <input placeholder="품목명 (선택 — DB 자동 비교)" value={wProduct} onChange={e => setWProduct(e.target.value)} list="product-list" />
            <datalist id="product-list">{PRODUCTS.map(p => <option key={p.id} value={p.name} />)}</datalist>
            <input type="number" placeholder="가격 (원, 선택)" value={wPrice} onChange={e => setWPrice(e.target.value)} />
          </div>

          {/* 이미지 업로드 */}
          <div className={s.imgUpload}>
            <button className={s.imgBtn} onClick={() => fileRef.current?.click()}><ImagePlus size={18} /> 사진 추가</button>
            <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={handleImageAdd} />
            {wImages.length > 0 && (
              <div className={s.imgPreview}>
                {wImages.map((src, i) => (
                  <div key={i} className={s.previewWrap}>
                    <img src={src} alt="" />
                    <button className={s.removeImg} onClick={() => setWImages(prev => prev.filter((_, j) => j !== i))}>×</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 자동 검증 결과 */}
          {verification && (
            <div className={s.verifyResult} style={{ background: VERIFY_STYLES[verification.status]?.bg || 'var(--glass)', color: VERIFY_STYLES[verification.status]?.color || 'var(--text)' }}>
              <span>{verification.emoji}</span>
              <span>{verification.label}</span>
              {matchedProduct && <span className={s.verifyDetail}>DB 평균: {fmt(matchedProduct.avg)}원</span>}
            </div>
          )}
          {!matchedProduct && wProduct && (
            <div className={s.noMatch}>ℹ️ DB에 없는 품목입니다. 검증 없이 등록됩니다.</div>
          )}
          {verification && !verification.canPost && (
            <div className={s.blocked}>⛔ 등록 차단됨 — 허위 가격이 의심됩니다.</div>
          )}

          <button className={s.submitBtn} onClick={handleWrite} disabled={verification?.canPost === false}>등록</button>
        </div>
      )}

      <div className={s.filterRow}>
        {TABS.map(t => (
          <button key={t} className={`${s.tab} ${filter === t ? s.tabActive : ''}`} onClick={() => setFilter(t)}>{t}</button>
        ))}
      </div>
      <div className={s.list}>
        {filtered.map(p => (
          <div key={p.id} className={s.post} onClick={() => setDetail(p)}>
            <span className={s.postCat}>{p.cat}</span>
            <div className={s.postBody}>
              <div className={s.postTitle}>
                {p.verified && <span className={s.verifyBadge} style={{ background: VERIFY_STYLES[p.verified]?.bg, color: VERIFY_STYLES[p.verified]?.color }}>
                  {VERIFY_STYLES[p.verified]?.icon}
                </span>}
                {p.title}
              </div>
              {p.body && <p className={s.postExcerpt}>{p.body.slice(0, 60)}...</p>}
              <div className={s.postMeta}>
                <span>{p.author}</span><span>{p.time}</span>
                <span>조회 {p.views}</span><span>💬 {p.commentData?.length || p.comments}</span>
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

      {detail && <DetailModal item={detail} type="community" onClose={() => setDetail(null)} />}
    </div>
  );
}
