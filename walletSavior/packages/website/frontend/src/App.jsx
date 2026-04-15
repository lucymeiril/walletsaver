import { Routes, Route } from 'react-router-dom';
import { lazy, Suspense, useEffect } from 'react';
import Header from './components/layout/Header';
import Footer from './components/layout/Footer';
import BottomNav from './components/layout/BottomNav';
import ToastContainer from './components/common/ToastContainer';
import LoginModal from './components/modals/LoginModal';
import useStore from './stores/appStore';
import { api } from './services/api';
import { authService } from './services/authService';
import { decodeTokenPayload, isTokenExpiringSoon } from './utils/tokenUtils';
import ShoppingListPanel from './components/common/ShoppingListPanel';
import ModalManager from './components/modals/ModalManager';
import ErrorBoundary from './components/common/ErrorBoundary';

// Lazy-load 페이지 (코드 스플리팅 — 초기 로드 최소화)
const HomePage      = lazy(() => import('./pages/Home/HomePage'));
const PricePage     = lazy(() => import('./pages/Price/PricePage'));
const CategoryComparePage = lazy(() => import('./pages/Price/CategoryComparePage'));
const HotdealPage   = lazy(() => import('./pages/Hotdeal/HotdealPage'));
const MartPage      = lazy(() => import('./pages/Mart/MartPage'));
const LocalPage     = lazy(() => import('./pages/Local/LocalPage'));
const CommunityPage = lazy(() => import('./pages/Community/CommunityPage'));
const SearchPage    = lazy(() => import('./pages/Search/SearchPage'));
const AuthCallback  = lazy(() => import('./pages/Auth/AuthCallback'));
const NotFoundPage  = lazy(() => import('./pages/NotFound/NotFoundPage'));

function PageLoader() {
  return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'center', minHeight:'60vh', color:'var(--text3)' }}>
      <div className="spinner" />
    </div>
  );
}

function Guarded({ children, name }) {
  return (
    <ErrorBoundary
      key={name}
      fallbackMessage={`${name} 페이지에서 오류가 발생했습니다.`}
      onReset={() => window.location.reload()}
    >
      {children}
    </ErrorBoundary>
  );
}

export default function App() {
  const theme = useStore((s) => s.theme);
  const login = useStore((s) => s.login);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Restore session from stored token on app mount
  useEffect(() => {
    const token = sessionStorage.getItem('access_token');
    if (token) {
      const payload = decodeTokenPayload(token);
      if (payload && !isTokenExpiringSoon(token, 0)) {
        api.setToken(token);
        login({ id: parseInt(payload.sub), email: payload.email, nickname: payload.nickname || payload.email?.split('@')[0], role: payload.role });
        authService.getProfile().then((profile) => login({ ...profile })).catch((err) => console.error('프로필 조회 실패:', err));
      } else {
        api.refreshToken().then((ok) => {
          if (ok) {
            const newToken = sessionStorage.getItem('access_token');
            const p = decodeTokenPayload(newToken);
            if (p) {
              login({ id: parseInt(p.sub), email: p.email, nickname: p.nickname || p.email?.split('@')[0], role: p.role });
              authService.getProfile().then((profile) => login({ ...profile })).catch((err) => console.error('프로필 조회 실패:', err));
            }
          }
        });
      }
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <Header />
      <main style={{ paddingTop: 'var(--hdr-h)' }}>
        <ErrorBoundary fallbackMessage="앱에서 오류가 발생했습니다. 페이지를 새로고침 해주세요.">
          <Suspense fallback={<PageLoader />}>
            <Routes>
              <Route path="/"          element={<Guarded name="홈"><HomePage /></Guarded>} />
              <Route path="/search"    element={<Guarded name="검색"><SearchPage /></Guarded>} />
              <Route path="/price"     element={<Guarded name="물가비교"><PricePage /></Guarded>} />
              <Route path="/price/category/:categoryId" element={<Guarded name="카테고리"><CategoryComparePage /></Guarded>} />
              <Route path="/price/:id" element={<Guarded name="물가비교"><PricePage /></Guarded>} />
              <Route path="/hotdeal"   element={<Guarded name="핫딜"><HotdealPage /></Guarded>} />
              <Route path="/mart"      element={<Guarded name="마트"><MartPage /></Guarded>} />
              <Route path="/local"     element={<Guarded name="내주변"><LocalPage /></Guarded>} />
              <Route path="/community" element={<Guarded name="커뮤니티"><CommunityPage /></Guarded>} />
              <Route path="/auth/callback" element={<AuthCallback />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </main>
      <Footer />
      <BottomNav />
      <ToastContainer />
      <LoginModal />
      <ShoppingListPanel />
      <ModalManager />
    </>
  );
}
