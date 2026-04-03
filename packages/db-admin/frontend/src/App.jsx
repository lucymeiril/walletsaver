import { Routes, Route } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import AdminLayout from './layouts/AdminLayout';

const Dashboard  = lazy(() => import('./pages/Dashboard/Dashboard'));
const Products   = lazy(() => import('./pages/Products/Products'));
const Prices     = lazy(() => import('./pages/Prices/Prices'));
const Categories = lazy(() => import('./pages/Categories/Categories'));
const Keywords   = lazy(() => import('./pages/Keywords/Keywords'));
const Analytics  = lazy(() => import('./pages/Analytics/Analytics'));
const InboxPage  = lazy(() => import('./pages/Inbox/InboxPage'));

function Loader() {
  return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'center', minHeight:'40vh', color:'var(--text3)' }}>
      로딩 중...
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<Loader />}>
      <Routes>
        <Route element={<AdminLayout />}>
          <Route path="/"           element={<Dashboard />} />
          <Route path="/inbox"      element={<InboxPage />} />
          <Route path="/products"   element={<Products />} />
          <Route path="/prices"     element={<Prices />} />
          <Route path="/categories" element={<Categories />} />
          <Route path="/keywords"   element={<Keywords />} />
          <Route path="/analytics"  element={<Analytics />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
