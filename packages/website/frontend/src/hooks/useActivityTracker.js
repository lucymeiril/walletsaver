/**
 * 활동 추적 훅 — 사용자 행동을 /api/activity/track 으로 전송
 * Rate limited: 최소 5초 간격, 로그인 시에만 동작
 */
import { useCallback, useRef } from 'react';
import { api } from '../services/api';
import useStore from '../stores/appStore';

const MIN_INTERVAL = 5000; // 5초

export default function useActivityTracker() {
  const isLoggedIn = useStore((s) => s.isLoggedIn);
  const lastCall = useRef(0);

  const track = useCallback(
    async (activityType, targetType, targetId, metadata = {}) => {
      if (!isLoggedIn) return;
      const now = Date.now();
      if (now - lastCall.current < MIN_INTERVAL) return;
      lastCall.current = now;
      try {
        await api.post('/api/activity/track', {
          activity_type: activityType,
          target_type: targetType,
          target_id: targetId,
          metadata,
        });
      } catch {
        // 추적 실패는 무시
      }
    },
    [isLoggedIn]
  );

  const trackView = useCallback(
    (targetType, targetId) => track('view', targetType, targetId),
    [track]
  );

  const trackSearch = useCallback(
    (query, resultCount) =>
      track('search', 'query', query, { result_count: resultCount }),
    [track]
  );

  const trackCartAdd = useCallback(
    (productId, productName) =>
      track('cart_add', 'product', productId, { name: productName }),
    [track]
  );

  const trackWishlistAdd = useCallback(
    (productId, productName) =>
      track('wishlist_add', 'product', productId, { name: productName }),
    [track]
  );

  return { track, trackView, trackSearch, trackCartAdd, trackWishlistAdd };
}
