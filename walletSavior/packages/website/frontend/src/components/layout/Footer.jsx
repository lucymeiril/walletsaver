import s from './Footer.module.css';

export default function Footer() {
  return (
    <footer className={s.ftr}>
      <div className={s.inner}>
        <div className={s.left}>
          <strong>지갑 지키미</strong>
          <p>정부 공식 물가 + 마트 전단 기반 가격 비교 서비스</p>
          <p className={s.copy}>© 2026 졸업작품 — 데이터 출처: KAMIS, OPINET, KOSIS</p>
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
