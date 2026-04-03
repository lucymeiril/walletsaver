import { Routes, Route } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import Header from './components/layout/Header';
import Footer from './components/layout/Footer';
import BottomNav from './components/layout/BottomNav';
import ToastContainer from './components/common/ToastContainer';
import LoginModal from './components/modals/LoginModal';

// Lazy-load 페이지 (코드 스플리팅 — 초기 로드 최소화)
const HomePage      = lazy(() => import('./pages/HomePage'));
const PricePage     = lazy(() => import('./pages/PricePage'));
const HotdealPage   = lazy(() => import('./pages/HotdealPage'));
const MartPage      = lazy(() => import('./pages/MartPage'));
const LocalPage     = lazy(() => import('./pages/LocalPage'));
const CommunityPage = lazy(() => import('./pages/CommunityPage'));

function PageLoader() {
  return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'center', minHeight:'60vh', color:'var(--text3)' }}>
      <div className="spinner" />
    </div>
  );
}

export default function App() {
  return (
    <>
      <Header />
      <main style={{ paddingTop: 'var(--hdr-h)' }}>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/"          element={<HomePage />} />
            <Route path="/price"     element={<PricePage />} />
            <Route path="/price/:id" element={<PricePage />} />
            <Route path="/hotdeal"   element={<HotdealPage />} />
            <Route path="/mart"      element={<MartPage />} />
            <Route path="/local"     element={<LocalPage />} />
            <Route path="/community" element={<CommunityPage />} />
          </Routes>
        </Suspense>
      </main>
      <Footer />
      <BottomNav />
      <ToastContainer />
      <LoginModal />
    </>
  );
}
