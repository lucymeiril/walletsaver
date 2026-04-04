/**
 * PluginMarketplace — 플러그인 마켓플레이스 UI
 */

import { useState, useMemo, useCallback, memo } from 'react';
import { Search, Download, Trash2, Star, Package, Filter } from 'lucide-react';
import { usePluginStore } from './PluginStore.js';
import s from './PluginMarketplace.module.css';

/** 카테고리 목록 */
const CATEGORIES = [
  { id: 'all', label: '전체' },
  { id: 'widget', label: '위젯' },
  { id: 'theme', label: '테마' },
  { id: 'tool', label: '도구' },
  { id: 'alert', label: '알림' },
];

/** 데모 플러그인 데이터 */
const DEMO_PLUGINS = [
  {
    id: 'price-alert-widget',
    name: '가격 알림 위젯',
    description: '관심 상품의 가격 변동을 실시간으로 알려주는 위젯입니다.',
    author: 'WalletSavior 팀',
    version: '1.0.0',
    category: 'alert',
    rating: 4.8,
    downloads: 1520,
    icon: '🔔',
    slot: 'dashboard-widget',
    permissions: ['read:products', 'read:prices'],
  },
  {
    id: 'deal-timer',
    name: '핫딜 타이머',
    description: '만료 임박 핫딜의 남은 시간을 카운트다운으로 보여줍니다.',
    author: 'WalletSavior 팀',
    version: '1.0.0',
    category: 'widget',
    rating: 4.5,
    downloads: 980,
    icon: '⏱️',
    slot: 'hotdeal-card-extra',
    permissions: ['read:hotdeals'],
  },
  {
    id: 'custom-theme',
    name: '커스텀 테마',
    description: '나만의 색상과 글꼴 크기로 사이트를 꾸밀 수 있습니다.',
    author: 'WalletSavior 팀',
    version: '1.0.0',
    category: 'theme',
    rating: 4.2,
    downloads: 2340,
    icon: '🎨',
    slot: 'sidebar',
    permissions: ['write:preferences'],
  },
  {
    id: 'price-chart-pro',
    name: '가격 차트 프로',
    description: '상세 가격 추이 차트와 예측 기능을 제공합니다.',
    author: '분석왕',
    version: '2.1.0',
    category: 'tool',
    rating: 4.9,
    downloads: 3100,
    icon: '📊',
    slot: 'price-overlay',
    permissions: ['read:products', 'read:prices', 'network:internal'],
  },
  {
    id: 'deal-share',
    name: '핫딜 공유',
    description: 'SNS로 핫딜 정보를 쉽게 공유할 수 있는 플러그인입니다.',
    author: '공유맨',
    version: '1.2.0',
    category: 'tool',
    rating: 3.9,
    downloads: 750,
    icon: '📤',
    slot: 'hotdeal-card-extra',
    permissions: ['read:hotdeals', 'network:external'],
  },
  {
    id: 'savings-tracker',
    name: '절약 추적기',
    description: '지금까지 절약한 금액을 추적하고 목표를 설정할 수 있습니다.',
    author: '절약왕',
    version: '1.0.0',
    category: 'widget',
    rating: 4.6,
    downloads: 1800,
    icon: '💰',
    slot: 'dashboard-widget',
    permissions: ['read:products', 'write:preferences'],
  },
];

function StarRating({ rating }) {
  const full = Math.floor(rating);
  const hasHalf = rating - full >= 0.5;
  return (
    <span className={s.stars} aria-label={`${rating}점`}>
      {Array.from({ length: 5 }, (_, i) => (
        <Star
          key={i}
          size={14}
          fill={i < full ? 'var(--warning, #fbbf24)' : i === full && hasHalf ? 'url(#half)' : 'none'}
          color={i < full || (i === full && hasHalf) ? 'var(--warning, #fbbf24)' : 'var(--text3, #64748b)'}
        />
      ))}
      <span className={s.ratingValue}>{rating}</span>
    </span>
  );
}

const PluginCard = memo(function PluginCard({ plugin, isInstalled, onInstall, onUninstall }) {
  return (
    <div className={s.card}>
      <div className={s.cardIcon}>{plugin.icon}</div>
      <div className={s.cardBody}>
        <h3 className={s.cardTitle}>{plugin.name}</h3>
        <p className={s.cardDesc}>{plugin.description}</p>
        <div className={s.cardMeta}>
          <span className={s.author}>{plugin.author}</span>
          <span className={s.version}>v{plugin.version}</span>
        </div>
        <div className={s.cardFooter}>
          <StarRating rating={plugin.rating} />
          <span className={s.downloads}>
            <Download size={12} />
            {plugin.downloads.toLocaleString()}
          </span>
        </div>
      </div>
      <div className={s.cardActions}>
        {isInstalled ? (
          <button
            className={`${s.actionBtn} ${s.uninstallBtn}`}
            onClick={() => onUninstall(plugin.id)}
          >
            <Trash2 size={14} />
            제거
          </button>
        ) : (
          <button
            className={`${s.actionBtn} ${s.installBtn}`}
            onClick={() => onInstall(plugin)}
          >
            <Download size={14} />
            설치
          </button>
        )}
      </div>
    </div>
  );
});

export default memo(function PluginMarketplace() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const { plugins, installPlugin, uninstallPlugin } = usePluginStore();

  const installedIds = useMemo(
    () => new Set(plugins.map((p) => p.id)),
    [plugins]
  );

  const filteredPlugins = useMemo(() => {
    return DEMO_PLUGINS.filter((plugin) => {
      const matchesCategory =
        selectedCategory === 'all' || plugin.category === selectedCategory;
      const matchesSearch =
        !searchQuery ||
        plugin.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        plugin.description.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesCategory && matchesSearch;
    });
  }, [searchQuery, selectedCategory]);

  const handleInstall = useCallback((plugin) => {
    installPlugin({
      id: plugin.id,
      name: plugin.name,
      version: plugin.version,
      description: plugin.description,
      author: plugin.author,
      slot: plugin.slot,
      permissions: plugin.permissions,
      entry: `plugins/examples/${plugin.id}/index.html`,
      config: {},
    });
  }, [installPlugin]);

  const handleUninstall = useCallback((pluginId) => {
    uninstallPlugin(pluginId);
  }, [uninstallPlugin]);

  return (
    <div className={s.marketplace}>
      <header className={s.header}>
        <h1 className={s.title}>
          <Package size={24} />
          플러그인 마켓플레이스
        </h1>
        <p className={s.subtitle}>나만의 플러그인으로 지갑 지키미를 확장하세요</p>
      </header>

      {/* 검색 및 필터 */}
      <div className={s.toolbar}>
        <div className={s.searchBox}>
          <Search size={18} className={s.searchIcon} />
          <input
            type="text"
            className={s.searchInput}
            placeholder="플러그인 검색..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className={s.categories}>
          <Filter size={16} />
          {CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              className={`${s.catBtn} ${selectedCategory === cat.id ? s.catActive : ''}`}
              onClick={() => setSelectedCategory(cat.id)}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </div>

      {/* 플러그인 그리드 */}
      <div className={s.grid}>
        {filteredPlugins.map((plugin) => (
          <PluginCard
            key={plugin.id}
            plugin={plugin}
            isInstalled={installedIds.has(plugin.id)}
            onInstall={handleInstall}
            onUninstall={handleUninstall}
          />
        ))}
        {filteredPlugins.length === 0 && (
          <div className={s.empty}>
            <Package size={48} />
            <p>검색 결과가 없습니다</p>
          </div>
        )}
      </div>
    </div>
  );
})

export { DEMO_PLUGINS, CATEGORIES };
