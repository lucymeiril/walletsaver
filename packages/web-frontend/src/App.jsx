import { Routes, Route } from 'react-router-dom';
import { lazy, Suspense, useEffect } from 'react';
import Header from './components/layout/Header';
import Footer from './components/layout/Footer';
import BottomNav from './components/layout/BottomNav';
import ToastContainer from './components/common/ToastContainer';
import LoginModal from './components/modals/LoginModal';
import useStore from './stores/appStore';
import useCartStore from './stores/cartStore';
import { authService } from './services/authService';
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
const ProfilePage   = lazy(() => import('./pages/Profile/ProfilePage'));
const WishlistPage  = lazy(() => import('./pages/Wishlist/WishlistPage'));
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
  const mergeOnLogin = useCartStore((s) => s.mergeOnLogin);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // 앱 부팅 시 세션 복원: 로그인 이력이 있을 때만 조용히 확인해 첫 화면의 401 잡음을 막는다.
  useEffect(() => {
    const demoProfile = localStorage.getItem('walletsavior-demo-profile');
    if (demoProfile) {
      try {
        login(JSON.parse(demoProfile));
        return;
      } catch {
        localStorage.removeItem('walletsavior-demo-profile');
      }
    }
    if (localStorage.getItem('walletsavior-auth-session') !== '1') return;
    authService.getProfile({ silent: true })
      .then((profile) => {
        login({ ...profile });
        mergeOnLogin();
      })
      .catch(() => {
        localStorage.removeItem('walletsavior-auth-session');
      });
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
              <Route path="/profile" element={<Guarded name="프로필"><ProfilePage /></Guarded>} />
              <Route path="/wishlist" element={<Guarded name="찜"><WishlistPage /></Guarded>} />
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
