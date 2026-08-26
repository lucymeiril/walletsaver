import { useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import useStore from '../../stores/appStore';
import { authService } from '../../services/authService';
import { syncAccountData } from '../../services/accountSync';

export default function AuthCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const login = useStore((s) => s.login);
  const addToast = useStore((s) => s.addToast);

  useEffect(() => {
    const error = params.get('error');

    if (error) {
      authService.clearLocalSession();
      addToast(error === 'oauth_config' ? 'OAuth 설정을 확인해주세요' : '소셜 로그인에 실패했습니다', 'error');
      navigate('/', { replace: true });
      return;
    }

    const finish = async () => {
      try {
        const profile = await authService.getProfile();
        login({ ...profile });
        authService.markSessionVerified();
        const failures = await syncAccountData();
        addToast('로그인 되었습니다! 🎉', 'success');
        if (failures.length > 0) {
          addToast(`${failures.join(', ')} 동기화에 실패했습니다.`, 'warning');
        }
      } catch {
        authService.clearLocalSession();
        addToast('로그인 정보를 확인하지 못했습니다', 'error');
      } finally {
        navigate('/', { replace: true });
      }
    };

    finish();
  }, [params, navigate, login, addToast]);

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', color: 'var(--text3)' }}>
      <div className="spinner" />
      <span style={{ marginLeft: 12 }}>로그인 처리 중...</span>
    </div>
  );
}
