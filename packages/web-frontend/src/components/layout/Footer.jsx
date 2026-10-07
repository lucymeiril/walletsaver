import s from './Footer.module.css';

export default function Footer() {
  return (
    <footer className={s.ftr}>
      <div className={s.inner}>
        <div className={s.left}>
          <strong>지갑 지키미</strong>
          <p>수집된 마트·공개 출처 가격 — 관측 시점 기준</p>
          <p className={s.copy}>© 2026 졸업작품 · 각 상품의 원문 출처와 구매 조건을 확인하세요</p>
        </div>
        <div className={s.links}>
          <a href="#">이용약관</a>
          <a href="#">개인정보처리방침</a>
          <a href="#">문의</a>
        </div>
      </div>
    </footer>
  );
}
