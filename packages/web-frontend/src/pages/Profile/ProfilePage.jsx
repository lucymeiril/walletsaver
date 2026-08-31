/**
 * 프로필 페이지 — 회원 정보 조회/수정, 활동 내역, 계정 관리
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  User, Mail, Calendar, Edit3, Save, X, LogOut, Trash2,
  Eye, Search, ThumbsUp, ShoppingCart, Heart, Clock,
  ChevronLeft, ChevronRight, AlertTriangle, ArrowRight,
  BellRing,
} from 'lucide-react';
import useStore from '../../stores/appStore';
import { authService } from '../../services/authService';
import { api } from '../../services/api';
import { fmt } from '../../utils/helpers';
import s from './ProfilePage.module.css';

const TABS = [
  { key: 'info', label: '내 정보', icon: User },
  { key: 'activity', label: '활동 내역', icon: Clock },
  { key: 'wishlist', label: '찜 목록', icon: Heart },
  { key: 'alerts', label: '가격 알림', icon: BellRing },
  { key: 'account', label: '계정 관리', icon: AlertTriangle },
];

const ACTIVITY_ICONS = {
  view: Eye,
  search: Search,
  vote: ThumbsUp,
  cart_add: ShoppingCart,
  wishlist_add: Heart,
};

export default function ProfilePage() {
  const navigate = useNavigate();
  const { isLoggedIn, user, login, logout, addToast } = useStore();
  const [activeTab, setActiveTab] = useState(() => (
    new URLSearchParams(window.location.search).get('tab') === 'alerts' ? 'alerts' : 'info'
  ));
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ nickname: '', bio: '', profile_image_url: '' });
  const [saving, setSaving] = useState(false);
  const [activities, setActivities] = useState([]);
  const [activityPage, setActivityPage] = useState(1);
  const [activityTotal, setActivityTotal] = useState(0);
  const [activityLoading, setActivityLoading] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteInput, setDeleteInput] = useState('');
  const [wishlistItems, setWishlistItems] = useState([]);
  const [wishlistLoading, setWishlistLoading] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const [alertsLoading, setAlertsLoading] = useState(false);

  // Redirect if not logged in
  useEffect(() => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      navigate('/');
    }
  }, [isLoggedIn, navigate, addToast]);

  // Init form from user
  useEffect(() => {
    if (user) {
      setForm({
        nickname: user.nickname || '',
        bio: user.bio || '',
        profile_image_url: user.profile_image_url || user.profile_image || user.profileImage || '',
      });
    }
  }, [user]);

  // Fetch activities
  const fetchActivities = useCallback(async (page = 1) => {
    setActivityLoading(true);
    try {
      const data = await api.getJson('/api/profile/activity', { page, per_page: 10 });
      const responseData = data.data || data;
      setActivities(Array.isArray(responseData) ? responseData : []);
      const meta = data.meta || {};
      setActivityTotal(meta.total_pages || 1);
    } catch {
      setActivities([]);
    }
    setActivityLoading(false);
  }, []);

  useEffect(() => {
    if (activeTab === 'activity' && isLoggedIn) {
      fetchActivities(activityPage);
    }
  }, [activeTab, activityPage, isLoggedIn, fetchActivities]);

  // Fetch wishlist
  useEffect(() => {
    if (activeTab !== 'wishlist' || !isLoggedIn) return;
    let cancelled = false;
    const fetchWishlist = async () => {
      setWishlistLoading(true);
      try {
        const data = await api.getJson('/api/wishlist', { per_page: 5 });
        if (!cancelled) {
          const items = data.data || data.items || (Array.isArray(data) ? data : []);
          setWishlistItems(items);
        }
      } catch {
        if (!cancelled) setWishlistItems([]);
      }
      if (!cancelled) setWishlistLoading(false);
    };
    fetchWishlist();
    return () => { cancelled = true; };
  }, [activeTab, isLoggedIn]);

  const fetchAlerts = useCallback(async () => {
    setAlertsLoading(true);
    try {
      const response = await api.getJson('/api/users/me/alerts', null, { silent: true });
      const rows = response?.data || response || [];
      setAlerts(Array.isArray(rows) ? rows : []);
    } catch {
      setAlerts([]);
    } finally {
      setAlertsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'alerts' && isLoggedIn) fetchAlerts();
  }, [activeTab, isLoggedIn, fetchAlerts]);

  const removeAlert = async (alertId) => {
    try {
      await api.delete(`/api/users/me/alerts/${alertId}`);
      setAlerts((rows) => rows.filter((row) => row.id !== alertId));
      addToast('가격 알림을 해제했습니다', 'info');
    } catch (error) {
      addToast(error?.message || '가격 알림 해제에 실패했습니다', 'error');
    }
  };

  const handleSave = async () => {
    if (form.nickname.length < 2 || form.nickname.length > 20) {
      addToast('닉네임은 2~20자여야 합니다', 'error');
      return;
    }
    setSaving(true);
    try {
      const res = await api.put('/api/profile', {
        nickname: form.nickname,
        bio: form.bio,
        profile_image_url: form.profile_image_url,
      });
      const result = await res.json();
      const updated = result.data || result;
      login({ ...user, ...updated });
      addToast('프로필을 수정했습니다 ✅', 'success');
      setEditing(false);
    } catch (err) {
      addToast(err.message || '프로필 수정에 실패했습니다', 'error');
    }
    setSaving(false);
  };

  const handleLogout = async () => {
    try {
      await authService.logout();
    } catch { /* ignore */ }
    logout();
    addToast('로그아웃 되었습니다', 'info');
    navigate('/');
  };

  const handleDeleteAccount = async () => {
    if (deleteInput !== '탈퇴합니다') {
      addToast('"탈퇴합니다"를 정확히 입력해주세요', 'error');
      return;
    }
    try {
      await api.delete('/api/profile');
      logout();
      addToast('계정 탈퇴가 처리되었습니다', 'info');
      navigate('/');
    } catch (err) {
      addToast(err.message || '계정 탈퇴 처리에 실패했습니다', 'error');
    }
  };

  const memberSince = user?.created_at || user?.createdAt;
  const formattedDate = memberSince
    ? new Date(memberSince).toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
    : null;

  if (!isLoggedIn) return null;

  return (
    <div className={s.page}>
      <div className={s.container}>
        {/* Profile header */}
        <div className={s.profileHeader}>
          <div className={s.avatarWrap}>
            {form.profile_image_url ? (
              <img src={form.profile_image_url} alt="프로필" className={s.avatar} />
            ) : (
              <div className={s.avatarPlaceholder}>
                {(user?.nickname || user?.email || 'U').charAt(0).toUpperCase()}
              </div>
            )}
          </div>
          <div className={s.profileMeta}>
            <h1 className={s.profileName}>{user?.nickname || user?.email || '사용자'}</h1>
            {user?.email && <p className={s.profileEmail}><Mail size={14} /> {user.email}</p>}
            {formattedDate && <p className={s.profileDate}><Calendar size={14} /> {formattedDate} 가입</p>}
          </div>
        </div>

        {/* Tabs */}
        <div className={s.tabs}>
          {TABS.map((tab) => (
            <button
              key={tab.key}
              className={`${s.tab} ${activeTab === tab.key ? s.tabActive : ''}`}
              onClick={() => setActiveTab(tab.key)}
            >
              <tab.icon size={16} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Info tab */}
        {activeTab === 'info' && (
          <div className={s.tabContent}>
            <div className={s.sectionHeader}>
              <h2 className={s.sectionTitle}>기본 정보</h2>
              {!editing ? (
                <button className={s.editBtn} onClick={() => setEditing(true)}>
                  <Edit3 size={16} /> 수정
                </button>
              ) : (
                <div className={s.editActions}>
                  <button className={s.saveBtn} onClick={handleSave} disabled={saving}>
                    <Save size={16} /> {saving ? '저장 중...' : '저장'}
                  </button>
                  <button className={s.cancelBtn} onClick={() => { setEditing(false); setForm({ nickname: user?.nickname || '', bio: user?.bio || '', profile_image_url: user?.profile_image_url || user?.profile_image || '' }); }}>
                    <X size={16} /> 취소
                  </button>
                </div>
              )}
            </div>

            <div className={s.formGrid}>
              <div className={s.field}>
                <label className={s.fieldLabel}>닉네임</label>
                {editing ? (
                  <input
                    className={s.input}
                    value={form.nickname}
                    onChange={(e) => setForm({ ...form, nickname: e.target.value })}
                    maxLength={20}
                    minLength={2}
                    placeholder="2~20자"
                  />
                ) : (
                  <span className={s.fieldValue}>{user?.nickname || '-'}</span>
                )}
                {editing && (
                  <span className={s.charCount}>{form.nickname.length}/20</span>
                )}
              </div>

              <div className={s.field}>
                <label className={s.fieldLabel}>이메일</label>
                <span className={s.fieldValue}>{user?.email || '-'}</span>
              </div>

              <div className={s.field}>
                <label className={s.fieldLabel}>자기소개</label>
                {editing ? (
                  <textarea
                    className={s.textarea}
                    value={form.bio}
                    onChange={(e) => setForm({ ...form, bio: e.target.value })}
                    maxLength={200}
                    rows={3}
                    placeholder="간단한 자기소개를 입력하세요"
                  />
                ) : (
                  <span className={s.fieldValue}>{user?.bio || '아직 자기소개가 없어요'}</span>
                )}
              </div>

              <div className={s.field}>
                <label className={s.fieldLabel}>프로필 이미지 URL</label>
                {editing ? (
                  <input
                    className={s.input}
                    value={form.profile_image_url}
                    onChange={(e) => setForm({ ...form, profile_image_url: e.target.value })}
                    placeholder="https://..."
                    type="url"
                  />
                ) : (
                  <span className={s.fieldValue}>
                    {form.profile_image_url ? '설정됨' : '미설정'}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Activity tab */}
        {activeTab === 'activity' && (
          <div className={s.tabContent}>
            <h2 className={s.sectionTitle}>최근 활동</h2>
            {activityLoading ? (
              <div className={s.loadingState}>로딩 중...</div>
            ) : activities.length === 0 ? (
              <div className={s.emptyState}>
                <Clock size={40} />
                <p>아직 활동 내역이 없어요</p>
              </div>
            ) : (
              <>
                <div className={s.activityList}>
                  {activities.map((act, i) => {
                    const IconComp = ACTIVITY_ICONS[act.activity_type] || Eye;
                    return (
                      <div key={act.id || i} className={s.activityItem}>
                        <div className={s.activityIcon}>
                          <IconComp size={16} />
                        </div>
                        <div className={s.activityInfo}>
                          <span className={s.activityType}>
                            {act.activity_type === 'view' && '상품 조회'}
                            {act.activity_type === 'search' && '검색'}
                            {act.activity_type === 'vote' && '투표'}
                            {act.activity_type === 'cart_add' && '장바구니 추가'}
                            {act.activity_type === 'wishlist_add' && '찜 추가'}
                            {!['view', 'search', 'vote', 'cart_add', 'wishlist_add'].includes(act.activity_type) && act.activity_type}
                          </span>
                          <span className={s.activityTarget}>
                            {act.metadata?.name || act.target_id || ''}
                          </span>
                        </div>
                        <span className={s.activityTime}>
                          {act.created_at ? new Date(act.created_at).toLocaleDateString('ko-KR') : ''}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div className={s.pagination}>
                  <button
                    className={s.pageBtn}
                    disabled={activityPage <= 1}
                    onClick={() => setActivityPage((p) => Math.max(1, p - 1))}
                  >
                    <ChevronLeft size={16} /> 이전
                  </button>
                  <span className={s.pageInfo}>{activityPage} / {activityTotal || 1}</span>
                  <button
                    className={s.pageBtn}
                    disabled={activityPage >= activityTotal}
                    onClick={() => setActivityPage((p) => p + 1)}
                  >
                    다음 <ChevronRight size={16} />
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Wishlist tab */}
        {activeTab === 'wishlist' && (
          <div className={s.tabContent}>
            <h2 className={s.sectionTitle}>찜 목록</h2>
            {wishlistLoading ? (
              <div className={s.loadingState}>로딩 중...</div>
            ) : wishlistItems.length === 0 ? (
              <div className={s.emptyState}>
                <Heart size={40} />
                <p>아직 찜한 상품이 없어요</p>
              </div>
            ) : (
              <div className={s.wishlistSummary}>
                {wishlistItems.map((item, i) => (
                  <div key={item.id || i} className={s.wishlistItem}>
                    <Heart size={16} color="#ef4444" fill="#ef4444" />
                    <span className={s.wishlistItemName}>
                      {item.product_name || item.item_name || item.name || '상품'}
                    </span>
                    {(item.price_at_add ?? item.item_price ?? item.price) != null && (
                      <span className={s.wishlistItemPrice}>
                        {fmt(item.price_at_add ?? item.item_price ?? item.price)}원
                      </span>
                    )}
                  </div>
                ))}
                <button className={s.wishlistMore} onClick={() => navigate('/wishlist')}>
                  전체 찜 목록 보기 <ArrowRight size={14} />
                </button>
              </div>
            )}
          </div>
        )}

        {/* Price alerts tab */}
        {activeTab === 'alerts' && (
          <div className={s.tabContent}>
            <h2 className={s.sectionTitle}>가격 알림</h2>
            <p className={s.accountDesc}>외부 발송 없이 현재 가격의 목표 도달 여부를 여기에서 확인합니다.</p>
            {alertsLoading ? (
              <div className={s.loadingState}>로딩 중...</div>
            ) : alerts.length === 0 ? (
              <div className={s.emptyState}>
                <BellRing size={40} />
                <p>설정한 가격 알림이 없어요</p>
              </div>
            ) : (
              <div className={s.alertList}>
                {alerts.map((alert) => (
                  <div key={alert.id} className={s.alertItem}>
                    <div className={s.alertInfo}>
                      <strong>{alert.product_name || alert.product?.name || `상품 ${alert.product_id}`}</strong>
                      <span>목표 {fmt(alert.target_price)}원 · 현재 {alert.current_price != null ? `${fmt(alert.current_price)}원` : '가격 없음'}</span>
                    </div>
                    <span className={alert.is_triggered ? s.alertReached : s.alertWaiting}>
                      {alert.is_triggered ? '목표 도달' : '대기 중'}
                    </span>
                    <button type="button" className={s.alertRemove} onClick={() => removeAlert(alert.id)}>
                      해제
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Account management tab */}
        {activeTab === 'account' && (
          <div className={s.tabContent}>
            <div className={s.accountSection}>
              <h3 className={s.accountTitle}>로그아웃</h3>
              <p className={s.accountDesc}>현재 세션에서 로그아웃합니다.</p>
              <button className={s.logoutBtn} onClick={handleLogout}>
                <LogOut size={16} /> 로그아웃
              </button>
            </div>

            <div className={s.dangerZone}>
              <h3 className={s.dangerTitle}>⚠️ 계정 탈퇴</h3>
              <p className={s.dangerDesc}>
                탈퇴 처리 후 계정은 비활성화되어 다시 로그인할 수 없습니다.
                게시글 등 서비스 기록은 운영상 보존될 수 있습니다.
              </p>
              {!showDeleteConfirm ? (
                <button
                  className={s.deleteBtn}
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  <Trash2 size={16} /> 계정 탈퇴
                </button>
              ) : (
                <div className={s.deleteConfirm}>
                  <p className={s.confirmText}>
                    확인을 위해 <strong>"탈퇴합니다"</strong>를 입력해주세요:
                  </p>
                  <input
                    className={s.confirmInput}
                    value={deleteInput}
                    onChange={(e) => setDeleteInput(e.target.value)}
                    placeholder="탈퇴합니다"
                  />
                  <div className={s.confirmActions}>
                    <button
                      className={s.confirmDeleteBtn}
                      onClick={handleDeleteAccount}
                      disabled={deleteInput !== '탈퇴합니다'}
                    >
                      탈퇴 처리
                    </button>
                    <button
                      className={s.confirmCancelBtn}
                      onClick={() => { setShowDeleteConfirm(false); setDeleteInput(''); }}
                    >
                      취소
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
