import { BrowserRouter, Routes, Route } from 'react-router-dom'
import HomePage from './pages/HomePage'
import CategoryPage from './pages/CategoryPage'
import ProductDetailPage from './pages/ProductDetailPage'
import NavBar from './components/NavBar'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import AccountPage from './pages/AccountPage'
import BoardListPage from './pages/BoardListPage'
import BoardPage from './pages/BoardPage'
import NewPostPage from './pages/NewPostPage'
import PostDetailPage from './pages/PostDetailPage'
import AdminPage from './pages/AdminPage'
import FuelStationsPage from './pages/FuelStationsPage'
import { ModeProvider } from './context/ModeContext'

export default function App() {
  return (
    <ModeProvider>
    <BrowserRouter>
      <NavBar />
      <Routes>
        <Route path="/fuels" element={<FuelStationsPage />} />
        <Route path="/plugins" element={<PluginsPlaceholder />} />
        <Route path="/notifications" element={<NotificationsPlaceholder />} />
        <Route path="/restaurants" element={<RestaurantsPlaceholder />} />
        <Route path="/compare" element={<ComparePlaceholder />} />
        <Route path="/" element={<HomePage />} />
        <Route path="/c/:slug" element={<CategoryPage />} />
        <Route path="/p/:canonical_id" element={<ProductDetailPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/boards" element={<BoardListPage />} />
        <Route path="/board/:slug" element={<BoardPage />} />
        <Route path="/board/:slug/new" element={<NewPostPage />} />
        <Route path="/post/:id" element={<PostDetailPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Routes>
    </BrowserRouter>
    </ModeProvider>
  )
}

// web-FINAL §2: P1+ 자리 — 라우트만 박아 404 방지.
function PluginsPlaceholder() {
  return <div style={{ padding: 24, maxWidth: 720, margin: '0 auto' }}><h2>플러그인 마켓</h2><p style={{ color: '#6b7280' }}>P2 — 마켓 본격 오픈 예정. 현재는 상품 상세/마이페이지의 슬롯에서 위젯이 작동합니다.</p></div>
}
function NotificationsPlaceholder() {
  return <div style={{ padding: 24, maxWidth: 720, margin: '0 auto' }}><h2>알림함</h2><p style={{ color: '#6b7280' }}>P1 — 알림 발송 예정. 현재는 저장만.</p></div>
}
function RestaurantsPlaceholder() {
  return <div style={{ padding: 24, maxWidth: 720, margin: '0 auto' }}><h2>식당</h2><p style={{ color: '#6b7280' }}>v1.5 본격. 비교 조합기에서 "식당 가격 직접 입력"으로 사용하세요.</p></div>
}
function ComparePlaceholder() {
  return <div style={{ padding: 24, maxWidth: 720, margin: '0 auto' }}><h2>비교 조합기</h2><p style={{ color: '#6b7280' }}>P0 진입 자리. 프리셋 6개(김치찌개/된장찌개/제육볶음/샐러드/카레/파스타) + 자유 추가는 후속 작업.</p></div>
}
