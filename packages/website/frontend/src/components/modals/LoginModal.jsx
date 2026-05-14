import { useState, useMemo } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import useStore from '../../stores/appStore';
import { authService } from '../../services/authService';
import Modal from '../common/Modal';
import s from './LoginModal.module.css';

const GOOGLE_ICON = (
  <svg width="18" height="18" viewBox="0 0 24 24">
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
    <path d="M5.84 14.09a7.18 7.18 0 010-4.18V7.07H2.18A11.97 11.97 0 001 12c0 1.94.46 3.77 1.18 5.42l3.66-2.84z" fill="#FBBC05"/>
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
  </svg>
);

const isValidEmail = (email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

export default function LoginModal() {
  const [tab, setTab] = useState('login');
  const { login, addToast, isLoginModalOpen, closeLoginModal } = useStore();

  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginShowPw, setLoginShowPw] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState('');

  const [signupEmail, setSignupEmail] = useState('');
  const [signupNickname, setSignupNickname] = useState('');
  const [signupPassword, setSignupPassword] = useState('');
  const [signupConfirm, setSignupConfirm] = useState('');
  const [signupShowPw, setSignupShowPw] = useState(false);
  const [signupLoading, setSignupLoading] = useState(false);
  const [signupError, setSignupError] = useState('');

  const pwChecks = useMemo(() => ({
    length: signupPassword.length >= 8,
    upper: /[A-Z]/.test(signupPassword),
    lower: /[a-z]/.test(signupPassword),
    number: /[0-9]/.test(signupPassword),
  }), [signupPassword]);

  const pwStrength = useMemo(() => {
    const score = Object.values(pwChecks).filter(Boolean).length;
    if (score <= 1) return 'Weak';
    if (score <= 3) return 'Medium';
    return 'Strong';
  }, [pwChecks]);

  const pwMatch = signupConfirm.length > 0 && signupPassword === signupConfirm;
  const pwMismatch = signupConfirm.length > 0 && signupPassword !== signupConfirm;

  const completeLogin = async () => {
    try {
      const profile = await authService.getProfile();
      login({ ...profile });
    } catch {
      // Fallback: user is authenticated but profile fetch failed
      login({ email: 'unknown' });
    }
    addToast('로그인 되었습니다! 🎉', 'success');
    closeLoginModal();
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginError('');
    if (!isValidEmail(loginEmail)) { setLoginError('올바른 이메일 형식을 입력해주세요'); return; }
    setLoginLoading(true);
    try {
      const data = await authService.login(loginEmail, loginPassword);
      await completeLogin(data);
    } catch (err) {
      setLoginError(err.data?.detail || '이메일 또는 비밀번호가 올바르지 않습니다');
    } finally {
      setLoginLoading(false);
    }
  };

  const handleSignup = async (e) => {
    e.preventDefault();
    setSignupError('');
    if (!isValidEmail(signupEmail)) { setSignupError('올바른 이메일 형식을 입력해주세요'); return; }
    if (signupNickname.length < 2 || signupNickname.length > 20) { setSignupError('닉네임은 2~20자여야 합니다'); return; }
    if (!Object.values(pwChecks).every(Boolean)) { setSignupError('비밀번호 조건을 모두 충족해주세요'); return; }
    if (signupPassword !== signupConfirm) { setSignupError('비밀번호가 일치하지 않습니다'); return; }
    setSignupLoading(true);
    try {
      const data = await authService.register({ email: signupEmail, nickname: signupNickname, password: signupPassword });
      await completeLogin(data);
    } catch (err) {
      const detail = err.data?.detail || '';
      if (typeof detail === 'string' && (detail.includes('email') || detail.includes('이메일'))) {
        setSignupError('이미 사용 중인 이메일입니다');
      } else if (typeof detail === 'string' && (detail.includes('nickname') || detail.includes('닉네임'))) {
        setSignupError('이미 사용 중인 닉네임입니다');
      } else {
        setSignupError(typeof detail === 'string' && detail ? detail : '회원가입에 실패했습니다');
      }
    } finally {
      setSignupLoading(false);
    }
  };

  const handleOAuth = (provider) => {
    // OAuth는 Vite 프록시를 거치지 않고 백엔드로 직접 리다이렉트
    // (프록시가 302를 소비하면 Google로 리다이렉트되지 않음)
    const backendUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    window.location.href = `${backendUrl}/api/auth/oauth/${provider}`;
  };

  const switchTab = (t) => {
    setTab(t);
    setLoginEmail(''); setLoginPassword(''); setLoginError('');
    setSignupEmail(''); setSignupNickname(''); setSignupPassword(''); setSignupConfirm(''); setSignupError('');
  };

  return (
    <Modal isOpen={isLoginModalOpen} onClose={closeLoginModal} title={tab === 'login' ? '로그인' : '회원가입'} size="sm">
      <div className={s.tabs} role="tablist">
        <button role="tab" aria-selected={tab === 'login'} className={`${s.tab} ${tab === 'login' ? s.tabActive : ''}`} onClick={() => switchTab('login')}>로그인</button>
        <button role="tab" aria-selected={tab === 'signup'} className={`${s.tab} ${tab === 'signup' ? s.tabActive : ''}`} onClick={() => switchTab('signup')}>회원가입</button>
      </div>

      {tab === 'login' ? (
        <form className={s.form} onSubmit={handleLogin} noValidate>
          <div className={s.group}>
            <label>이메일</label>
            <input type="email" placeholder="example@email.com" value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)} required aria-label="이메일" />
          </div>
          <div className={s.group}>
            <label>비밀번호</label>
            <div className={s.passwordWrap}>
              <input type={loginShowPw ? 'text' : 'password'} placeholder="비밀번호" value={loginPassword} onChange={(e) => setLoginPassword(e.target.value)} required aria-label="비밀번호" />
              <button type="button" className={s.passwordToggle} onClick={() => setLoginShowPw(!loginShowPw)} aria-label={loginShowPw ? '비밀번호 숨기기' : '비밀번호 보기'}>
                {loginShowPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
          {loginError && <p className={s.error}>{loginError}</p>}
          <button type="submit" className={s.submitBtn} disabled={loginLoading}>
            {loginLoading ? '로그인 중...' : '로그인'}
          </button>
          <div className={s.divider}><span>또는</span></div>
          <button type="button" className={s.google} onClick={() => handleOAuth('google')}>{GOOGLE_ICON} 구글로 시작하기</button>
          <button type="button" className={s.kakao} onClick={() => handleOAuth('kakao')}>카카오로 시작하기</button>
          <button type="button" className={s.naver} onClick={() => handleOAuth('naver')}>네이버로 시작하기</button>
          <p className={s.switchLink}>계정이 없으신가요? <button type="button" onClick={() => switchTab('signup')}>회원가입</button></p>
        </form>
      ) : (
        <form className={s.form} onSubmit={handleSignup} noValidate>
          <div className={s.group}>
            <label>이메일</label>
            <input type="email" placeholder="example@email.com" value={signupEmail} onChange={(e) => setSignupEmail(e.target.value)} required aria-label="이메일" />
          </div>
          <div className={s.group}>
            <label>닉네임</label>
            <input type="text" placeholder="2~20자" value={signupNickname} onChange={(e) => setSignupNickname(e.target.value)} minLength={2} maxLength={20} required aria-label="닉네임" />
          </div>
          <div className={s.group}>
            <label>비밀번호</label>
            <div className={s.passwordWrap}>
              <input type={signupShowPw ? 'text' : 'password'} placeholder="8자 이상" value={signupPassword} onChange={(e) => setSignupPassword(e.target.value)} required aria-label="비밀번호" />
              <button type="button" className={s.passwordToggle} onClick={() => setSignupShowPw(!signupShowPw)} aria-label={signupShowPw ? '비밀번호 숨기기' : '비밀번호 보기'}>
                {signupShowPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {signupPassword.length > 0 && (
              <>
                <div className={s.strengthBar}><div className={`${s.strengthFill} ${s['strength' + pwStrength]}`} /></div>
                <div className={s.pwChecks}>
                  <span className={pwChecks.length ? s.checkPass : s.checkFail}>8자 이상</span>
                  <span className={pwChecks.upper ? s.checkPass : s.checkFail}>대문자 포함</span>
                  <span className={pwChecks.lower ? s.checkPass : s.checkFail}>소문자 포함</span>
                  <span className={pwChecks.number ? s.checkPass : s.checkFail}>숫자 포함</span>
                </div>
              </>
            )}
          </div>
          <div className={s.group}>
            <label>비밀번호 확인</label>
            <input type="password" placeholder="비밀번호 확인" value={signupConfirm} onChange={(e) => setSignupConfirm(e.target.value)} required aria-label="비밀번호 확인" />
            {pwMatch && <span className={s.matchOk}>비밀번호가 일치합니다</span>}
            {pwMismatch && <span className={s.matchBad}>비밀번호가 일치하지 않습니다</span>}
          </div>
          {signupError && <p className={s.error}>{signupError}</p>}
          <button type="submit" className={s.submitBtn} disabled={signupLoading}>
            {signupLoading ? '가입 중...' : '회원가입'}
          </button>
          <p className={s.switchLink}>이미 계정이 있으신가요? <button type="button" onClick={() => switchTab('login')}>로그인</button></p>
        </form>
      )}
    </Modal>
  );
}
