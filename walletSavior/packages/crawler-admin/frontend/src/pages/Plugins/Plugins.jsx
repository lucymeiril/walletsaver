import { useState, useEffect, useMemo, useRef } from 'react';
import useAdminStore from '../../stores/adminStore';
import { Code, ChevronDown, ChevronUp, Search, Settings, X } from 'lucide-react';
import styles from './Plugins.module.css';

const CATEGORIES = [
  { key: 'all', label: '전체' },
  { key: '마트', label: '마트' },
  { key: '핫딜', label: '핫딜' },
  { key: '쇼핑', label: '쇼핑' },
  { key: '공공', label: '공공' },
  { key: '위치', label: '위치' },
];

const DIFFICULTY_LABELS = {
  1: '쉬움 — HTTP 단순 요청',
  2: '보통 — DOM 파싱 필요',
  3: '어려움 — SPA/동적 렌더링',
  4: '매우 어려움 — 안티봇 우회',
};

// 검색 디바운스 지연 (ms)
const DEBOUNCE_MS = 300;

export default function Plugins() {
  const plugins = useAdminStore((s) => s.plugins);
  const fetchPlugins = useAdminStore((s) => s.fetchPlugins);
  const togglePlugin = useAdminStore((s) => s.togglePlugin);
  const updatePluginSettings = useAdminStore((s) => s.updatePluginSettings);
  const loading = useAdminStore((s) => s.pluginsLoading);
  const error = useAdminStore((s) => s.pluginsError);

  const [expandedYaml, setExpandedYaml] = useState(null);
  const [category, setCategory] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [editPlugin, setEditPlugin] = useState(null);
  const [editForm, setEditForm] = useState({ target_url: '', delay: 1, max_items: 100 });
  const debounceRef = useRef(null);

  useEffect(() => {
    fetchPlugins();
  }, [fetchPlugins]);

  // 디바운스: 검색 입력 시 300ms 후에만 필터 반영
  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, []);

  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setSearch(value), DEBOUNCE_MS);
  };

  const filtered = useMemo(() => {
    let list = plugins;
    if (category !== 'all') {
      list = list.filter((p) => p.category === category);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (p) =>
          (p.name || '').toLowerCase().includes(q) ||
          (p.description || '').toLowerCase().includes(q)
      );
    }
    return list;
  }, [plugins, category, search]);

  const openSettingsModal = (plugin) => {
    setEditForm({
      target_url: plugin.target_url || '',
      delay: plugin.delay ?? 1,
      max_items: plugin.max_items ?? 100,
    });
    setEditPlugin(plugin);
  };

  const handleSaveSettings = async () => {
    if (!editPlugin) return;
    await updatePluginSettings(editPlugin.id, editForm);
    setEditPlugin(null);
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.pageTitle}>플러그인 관리</h1>

      {error && (
        <div className={styles.errorBanner}>{error}</div>
      )}

      {/* 카테고리 필터 + 검색 */}
      <div className={styles.toolbar}>
        <div className={styles.categories}>
          {CATEGORIES.map((c) => (
            <button
              key={c.key}
              className={category === c.key ? styles.catBtnActive : styles.catBtn}
              onClick={() => setCategory(c.key)}
            >
              {c.label}
            </button>
          ))}
        </div>
        <div className={styles.searchBox}>
          <Search size={14} className={styles.searchIcon} />
          <input
            type="text"
            className={styles.searchInput}
            placeholder="플러그인 검색..."
            value={searchInput}
            onChange={handleSearchChange}
          />
        </div>
      </div>

      {loading && plugins.length === 0 ? (
        <div className={styles.emptyState}>플러그인 로딩 중...</div>
      ) : filtered.length === 0 ? (
        <div className={styles.emptyState}>
          {plugins.length === 0 ? '등록된 플러그인이 없습니다' : '조건에 맞는 플러그인이 없습니다'}
        </div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((plugin) => {
            const inactive = plugin.status !== 'active';
            return (
              <div
                key={plugin.id}
                className={`${styles.card} ${inactive ? styles.cardInactive : ''} ${plugin.isRunning ? styles.cardRunning : ''}`}
              >
                <div className={styles.cardHeader}>
                  <div className={styles.headerLeft}>
                    {plugin.isRunning && <span className={styles.runningDot} title="실행 중" />}
                    <span className={styles.pluginName}>{plugin.name}</span>
                  </div>
                  <span className={styles.version}>v{plugin.version}</span>
                </div>

                <p className={styles.description}>{plugin.description}</p>

                <div className={styles.meta}>
                  <span className={styles.author}>
                    {plugin.category && (
                      <span className={styles.categoryBadge}>[{plugin.category}]</span>
                    )}
                    by {plugin.author || 'WalletSavior'}
                  </span>
                  <span className={inactive ? styles.statusInactive : styles.statusActive}>
                    {plugin.isRunning ? '▶ 실행 중' : inactive ? '○ 비활성' : '● 활성'}
                  </span>
                </div>

                {/* 메타데이터 */}
                {(plugin.target_url || plugin.strategy || plugin.schedule_cron) && (
                  <div className={styles.metaGrid}>
                    {plugin.target_url && (
                      <>
                        <span>대상 URL:</span>
                        <span className={styles.metaEllipsis}>{plugin.target_url}</span>
                      </>
                    )}
                    {plugin.strategy && (
                      <>
                        <span>전략:</span>
                        <span>{plugin.strategy}</span>
                      </>
                    )}
                    {plugin.schedule_cron && plugin.schedule_cron !== 'manual' && (
                      <>
                        <span>스케줄:</span>
                        <span>{plugin.schedule_cron}</span>
                      </>
                    )}
                    {plugin.difficulty != null && (
                      <>
                        <span>난이도:</span>
                        <span
                          className={styles.difficultyStars}
                          title={DIFFICULTY_LABELS[plugin.difficulty] || `난이도 ${plugin.difficulty}`}
                        >
                          {'⭐'.repeat(Math.min(plugin.difficulty, 5))}
                          <span className={styles.tooltip}>
                            {DIFFICULTY_LABELS[plugin.difficulty] || `난이도 ${plugin.difficulty}`}
                          </span>
                        </span>
                      </>
                    )}
                    {plugin.output_model && (
                      <>
                        <span>출력 모델:</span>
                        <span>{plugin.output_model}</span>
                      </>
                    )}
                  </div>
                )}

                <div className={styles.toggleRow}>
                  <span className={styles.toggleLabel}>플러그인 활성화</span>
                  <button
                    className={plugin.status === 'active' ? styles.toggleOn : styles.toggle}
                    onClick={() => togglePlugin(plugin.id)}
                    aria-label={plugin.status === 'active' ? '비활성화' : '활성화'}
                  />
                </div>

                <div className={styles.actionRow}>
                  <button
                    className={styles.settingsBtn}
                    onClick={() => openSettingsModal(plugin)}
                  >
                    <Settings size={14} />
                    설정 편집
                  </button>

                  <button
                    className={styles.yamlToggle}
                    onClick={() =>
                      setExpandedYaml(expandedYaml === plugin.id ? null : plugin.id)
                    }
                  >
                    <Code size={14} />
                    plugin.yaml
                    {expandedYaml === plugin.id ? (
                      <ChevronUp size={14} />
                    ) : (
                      <ChevronDown size={14} />
                    )}
                  </button>
                </div>

                {expandedYaml === plugin.id && (
                  <div className={styles.yamlViewer}>
                    <code className={styles.yamlCode}>{plugin.config}</code>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 설정 편집 모달 */}
      {editPlugin && (
        <div className={styles.overlay} onClick={() => setEditPlugin(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2 className={styles.modalTitle}>설정 편집 — {editPlugin.name}</h2>
              <button className={styles.modalClose} onClick={() => setEditPlugin(null)}>
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <label className={styles.fieldLabel}>
                대상 URL
                <input
                  type="url"
                  className={styles.fieldInput}
                  value={editForm.target_url}
                  onChange={(e) => setEditForm({ ...editForm, target_url: e.target.value })}
                  placeholder="https://example.com"
                />
              </label>

              <label className={styles.fieldLabel}>
                요청 지연 (초)
                <input
                  type="number"
                  className={styles.fieldInput}
                  value={editForm.delay}
                  onChange={(e) => setEditForm({ ...editForm, delay: parseFloat(e.target.value) || 0 })}
                  min="0"
                  step="0.5"
                />
              </label>

              <label className={styles.fieldLabel}>
                최대 수집 수
                <input
                  type="number"
                  className={styles.fieldInput}
                  value={editForm.max_items}
                  onChange={(e) => setEditForm({ ...editForm, max_items: parseInt(e.target.value, 10) || 0 })}
                  min="1"
                />
              </label>
            </div>

            <div className={styles.modalFooter}>
              <button className={styles.cancelBtn} onClick={() => setEditPlugin(null)}>
                취소
              </button>
              <button className={styles.saveBtn} onClick={handleSaveSettings}>
                저장
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
