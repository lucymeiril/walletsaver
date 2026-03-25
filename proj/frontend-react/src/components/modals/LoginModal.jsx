import { useState } from 'react';
import useStore from '../../stores/appStore';
import s from './LoginModal.module.css';

export default function LoginModal() {
  const [tab, setTab] = useState('login');
  const { login, addToast } = useStore();

  const close = () => document.getElementById('modal-login')?.classList.remove('open');

  const handleLogin = (e) => {
    e.preventDefault();
    login({ name: '테스트유저', email: 'test@test.com' });
    addToast('로그인 되었습니다! (데모)', 'success');
    close();
  };

  const handleSignup = (e) => {
    e.preventDefault();
    addToast('회원가입이 완료되었습니다! (데모)', 'success');
    close();
  };

  return (
    <div className={s.modal} id="modal-login">
      <div className={s.overlay} onClick={close} />
      <div className={s.box}>
        <button className={s.close} onClick={close}>&times;</button>
        <div className={s.tabs}>
          <button className={`${s.tab} ${tab === 'login' ? s.tabActive : ''}`} onClick={() => setTab('login')}>로그인</button>
          <button className={`${s.tab} ${tab === 'signup' ? s.tabActive : ''}`} onClick={() => setTab('signup')}>회원가입</button>
        </div>

        {tab === 'login' ? (
          <form className={s.form} onSubmit={handleLogin}>
            <div className={s.group}><label>이메일</label><input type="email" placeholder="example@email.com" required /></div>
            <div className={s.group}><label>비밀번호</label><input type="password" placeholder="비밀번호" required /></div>
            <button type="submit" className={s.submitBtn}>로그인</button>
            <div className={s.divider}><span>또는</span></div>
            <button type="button" className={s.kakao}>카카오로 시작하기</button>
            <button type="button" className={s.naver}>네이버로 시작하기</button>
          </form>
        ) : (
          <form className={s.form} onSubmit={handleSignup}>
            <div className={s.group}><label>이메일</label><input type="email" placeholder="example@email.com" required /></div>
            <div className={s.group}><label>닉네임</label><input type="text" placeholder="닉네임" required /></div>
            <div className={s.group}><label>비밀번호</label><input type="password" placeholder="8자 이상" required /></div>
            <div className={s.group}><label>비밀번호 확인</label><input type="password" placeholder="비밀번호 확인" required /></div>
            <button type="submit" className={s.submitBtn}>회원가입</button>
          </form>
        )}
      </div>
    </div>
  );
}
