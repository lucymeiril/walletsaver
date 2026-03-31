import { BrowserRouter, Routes, Route } from 'react-router-dom';
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
      <Routes>
        <Route element={<AdminLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/crawlers" element={<Crawlers />} />
          <Route path="/data-review" element={<DataReviewPage />} />
          <Route path="/plugins" element={<Plugins />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/schedule" element={<Schedule />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
