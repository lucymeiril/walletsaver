import { Link } from 'react-router-dom';
import s from './NotFoundPage.module.css';

export default function NotFoundPage() {
  return (
    <div className={s.wrap}>
      <h1 className={s.code}>404</h1>
      <p className={s.msg}>페이지를 찾을 수 없습니다</p>
      <Link to="/" className={s.home}>홈으로 돌아가기</Link>
    </div>
  );
}
