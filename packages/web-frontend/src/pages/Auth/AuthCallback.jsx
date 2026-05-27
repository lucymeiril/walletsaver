import { useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import useStore from '../../stores/appStore';
import { authService } from '../../services/authService';

export default function AuthCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const login = useStore((s) => s.login);
  const addToast = useStore((s) => s.addToast);

  useEffect(() => {
    const error = params.get('error');
    const demo = params.get('demo');

    if (error) {
      addToast('소셜 로그인에 실패했습니다', 'error');
      navigate('/', { replace: true });
      return;
    }

    if (demo === '1') {
      const provider = params.get('provider') || 'google';
      authService.demoLogin(provider).then((profile) => {
        login(profile);
        addToast('OAuth 설정이 없어 데모 로그인으로 진행했습니다', 'info');
        navigate('/', { replace: true });
      }).catch(() => {
        addToast('데모 로그인 처리에 실패했습니다', 'error');
        navigate('/', { replace: true });
      });
      return;
    }

    // Tokens are now in httpOnly cookies — fetch profile to confirm auth
    authService.getProfile().then((profile) => {
      login({ ...profile });
      addToast('로그인 되었습니다! 🎉', 'success');
      navigate('/', { replace: true });
    }).catch(() => {
      addToast('로그인 정보를 받지 못했습니다', 'error');
      navigate('/', { replace: true });
    });
  }, [params, navigate, login, addToast]);

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', color: 'var(--text3)' }}>
      <div className="spinner" />
      <span style={{ marginLeft: 12 }}>로그인 처리 중...</span>
    </div>
  );
}
