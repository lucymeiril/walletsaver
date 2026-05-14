import { Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense, useEffect, useSyncExternalStore } from 'react';
import AdminLayout from './layouts/AdminLayout';
import ErrorBoundary from './components/ErrorBoundary';
import LoginPage from './pages/Login/LoginPage';
import { isAuthenticated, subscribe, autoLoginDev } from './stores/authStore';

const Dashboard          = lazy(() => import('./pages/Dashboard/Dashboard'));
const Products           = lazy(() => import('./pages/Products/Products'));
const Prices             = lazy(() => import('./pages/Prices/Prices'));
const ClassificationPage = lazy(() => import('./pages/Classification/ClassificationPage'));
const Analytics          = lazy(() => import('./pages/Analytics/Analytics'));
const InboxPage          = lazy(() => import('./pages/Inbox/InboxPage'));
const IntegrityPage      = lazy(() => import('./pages/Integrity/IntegrityPage'));
const CommunityModeration = lazy(() => import('./pages/Community/CommunityModeration'));

function Loader() {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      minHeight: '40vh', color: 'var(--text3)',
    }}>
      로딩 중...
    </div>
  );
}

function PageBoundary({ children }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<Loader />}>
        {children}
      </Suspense>
    </ErrorBoundary>
  );
}

function useAuth() {
  return useSyncExternalStore(subscribe, isAuthenticated);
}

export default function App() {
  const authed = useAuth();

  // 개발 환경 자동 로그인 시도
  useEffect(() => {
    if (!authed) {
      autoLoginDev();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!authed) {
    return (
      <ErrorBoundary message="애플리케이션에 심각한 오류가 발생했습니다.">
        <LoginPage />
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary message="애플리케이션에 심각한 오류가 발생했습니다.">
      <Suspense fallback={<Loader />}>
        <Routes>
          <Route element={<AdminLayout />}>
            <Route path="/"               element={<PageBoundary><Dashboard /></PageBoundary>} />
            <Route path="/inbox"          element={<PageBoundary><InboxPage /></PageBoundary>} />
            <Route path="/products"       element={<PageBoundary><Products /></PageBoundary>} />
            <Route path="/prices"         element={<PageBoundary><Prices /></PageBoundary>} />
            <Route path="/classification" element={<PageBoundary><ClassificationPage /></PageBoundary>} />
            <Route path="/categories"     element={<Navigate to="/classification" replace />} />
            <Route path="/keywords"       element={<Navigate to="/classification" replace />} />
            <Route path="/analytics"      element={<PageBoundary><Analytics /></PageBoundary>} />
            <Route path="/integrity"      element={<PageBoundary><IntegrityPage /></PageBoundary>} />
            <Route path="/community"      element={<PageBoundary><CommunityModeration /></PageBoundary>} />
          </Route>
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}
