import { useState } from 'react';
import { login } from '../../stores/authStore';
import s from './LoginPage.module.css';

export default function LoginPage() {
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(apiKey);
    } catch (err) {
      setError(err.message || 'API 키 인증에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={s.wrapper}>
      <div className={s.card}>
        <div className={s.header}>
          <div className={s.logoIcon}>WS</div>
          <h1 className={s.title}>크롤러 관리</h1>
          <p className={s.subtitle}>WalletSavior 크롤러 관리 시스템</p>
        </div>

        <form className={s.form} onSubmit={handleSubmit}>
          {error && <div className={s.error}>{error}</div>}

          <div className={s.field}>
            <label htmlFor="apiKey">API 키</label>
            <input
              id="apiKey"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="API 키를 입력하세요"
              required
              autoFocus
            />
          </div>

          <button type="submit" className={s.submitBtn} disabled={loading}>
            {loading ? '인증 중...' : '로그인'}
          </button>
        </form>
      </div>
    </div>
  );
}
