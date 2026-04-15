import { useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import useStore from '../../stores/appStore';
import { api } from '../../services/api';
import { authService } from '../../services/authService';
import { decodeTokenPayload } from '../../utils/tokenUtils';

export default function AuthCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const login = useStore((s) => s.login);
  const addToast = useStore((s) => s.addToast);

  useEffect(() => {
    const accessToken = params.get('access_token');
    const refreshToken = params.get('refresh_token');
    const error = params.get('error');

    if (error) {
      addToast('소셜 로그인에 실패했습니다', 'error');
      navigate('/', { replace: true });
      return;
    }

    if (accessToken && refreshToken) {
      api.setToken(accessToken);
      sessionStorage.setItem('access_token', accessToken);
      sessionStorage.setItem('refresh_token', refreshToken);

      const payload = decodeTokenPayload(accessToken);
      if (payload) {
        login({
          id: parseInt(payload.sub),
          email: payload.email,
          nickname: payload.email?.split('@')[0],
          role: payload.role,
        });
      }

      // Fetch full profile to get accurate nickname
      authService.getProfile().then((profile) => {
        login({ ...profile });
      }).catch((err) => console.error('프로필 조회 실패:', err));

      addToast('로그인 되었습니다! 🎉', 'success');
      navigate('/', { replace: true });
    } else {
      addToast('로그인 정보를 받지 못했습니다', 'error');
      navigate('/', { replace: true });
    }
  }, [params, navigate, login, addToast]);

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', color: 'var(--text3)' }}>
      <div className="spinner" />
      <span style={{ marginLeft: 12 }}>로그인 처리 중...</span>
    </div>
  );
}
