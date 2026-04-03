import { Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import AdminLayout from './layouts/AdminLayout';

const Dashboard        = lazy(() => import('./pages/Dashboard/Dashboard'));
const Products         = lazy(() => import('./pages/Products/Products'));
const Prices           = lazy(() => import('./pages/Prices/Prices'));
const ClassificationPage = lazy(() => import('./pages/Classification/ClassificationPage'));
const Analytics        = lazy(() => import('./pages/Analytics/Analytics'));
const InboxPage        = lazy(() => import('./pages/Inbox/InboxPage'));

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
          <Route path="/"               element={<Dashboard />} />
          <Route path="/inbox"          element={<InboxPage />} />
          <Route path="/products"       element={<Products />} />
          <Route path="/prices"         element={<Prices />} />
          <Route path="/classification" element={<ClassificationPage />} />
          <Route path="/categories"     element={<Navigate to="/classification" replace />} />
          <Route path="/keywords"       element={<Navigate to="/classification" replace />} />
          <Route path="/analytics"      element={<Analytics />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
