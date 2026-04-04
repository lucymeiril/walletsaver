import { BrowserRouter, Routes, Route } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import AdminLayout from './components/AdminLayout';
import Dashboard from './pages/Dashboard/Dashboard';
import Crawlers from './pages/Crawlers/Crawlers';
import Plugins from './pages/Plugins/Plugins';
import Logs from './pages/Logs/Logs';
import Schedule from './pages/Schedule/Schedule';
import DataReviewPage from './pages/DataReview/DataReviewPage';

export default function App() {
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
          </Route>
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
