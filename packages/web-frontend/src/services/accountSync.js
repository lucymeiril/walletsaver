import { api } from './api';
import useStore from '../stores/appStore';
import useCartStore from '../stores/cartStore';

/**
 * 로그인 직후 계정 소유 데이터를 DB와 맞춘다.
 * 장바구니는 게스트 상태의 로컬 항목을 한 번 병합하고,
 * 찜 목록은 DB를 단일 진실 소스로 다시 읽는다.
 */
export async function syncAccountData() {
  const failures = [];

  try {
    await useCartStore.getState().mergeOnLogin();
  } catch {
    failures.push('장바구니');
  }

  try {
    const result = await api.getJson('/api/wishlist');
    const items = result?.data || result?.items || result || [];
    useStore.getState().hydrateFavorites(Array.isArray(items) ? items : []);
  } catch {
    useStore.getState().hydrateFavorites([]);
    failures.push('찜 목록');
  }

  return [...new Set(failures)];
}
