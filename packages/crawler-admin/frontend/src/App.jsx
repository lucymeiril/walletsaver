import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useEffect, useSyncExternalStore } from 'react';
import ErrorBoundary from './components/ErrorBoundary';
import AdminLayout from './components/AdminLayout';
import LoginPage from './pages/Login/LoginPage';
import Dashboard from './pages/Dashboard/Dashboard';
import Crawlers from './pages/Crawlers/Crawlers';
import Plugins from './pages/Plugins/Plugins';
import Logs from './pages/Logs/Logs';
import Schedule from './pages/Schedule/Schedule';
import DataReviewPage from './pages/DataReview/DataReviewPage';
import RunHistory from './pages/RunHistory/RunHistory';
import AdHoc from './pages/AdHoc/AdHoc';
import WeeklyAlertsPage from './pages/WeeklyAlerts/WeeklyAlertsPage';
import { isAuthenticated, subscribe, autoLoginDev } from './stores/authStore';

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
      <ErrorBoundary>
        <LoginPage />
      </ErrorBoundary>
    );
  }

  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Routes>
          <Route element={<AdminLayout />}>
            <Route path="/" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
            <Route path="/crawlers" element={<ErrorBoundary><Crawlers /></ErrorBoundary>} />
            <Route path="/data-review" element={<ErrorBoundary><DataReviewPage /></ErrorBoundary>} />
            <Route path="/plugins" element={<ErrorBoundary><Plugins /></ErrorBoundary>} />
            <Route path="/logs" element={<ErrorBoundary><Logs /></ErrorBoundary>} />
            <Route path="/schedule" element={<ErrorBoundary><Schedule /></ErrorBoundary>} />
            <Route path="/runs" element={<ErrorBoundary><RunHistory /></ErrorBoundary>} />
            <Route path="/adhoc" element={<ErrorBoundary><AdHoc /></ErrorBoundary>} />
            {/* 주간 알림 — 사라진 SKU 목록 (cr3 신설) */}
            <Route path="/weekly-alerts" element={<ErrorBoundary><WeeklyAlertsPage /></ErrorBoundary>} />
          </Route>
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
