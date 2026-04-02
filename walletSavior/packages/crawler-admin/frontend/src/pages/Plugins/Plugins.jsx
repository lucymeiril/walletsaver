import { useState, useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { Code, ChevronDown, ChevronUp } from 'lucide-react';
import styles from './Plugins.module.css';

export default function Plugins() {
  const plugins = useAdminStore((s) => s.plugins);
  const fetchPlugins = useAdminStore((s) => s.fetchPlugins);
  const togglePlugin = useAdminStore((s) => s.togglePlugin);
  const loading = useAdminStore((s) => s.loading);
  const error = useAdminStore((s) => s.error);
  const [expandedYaml, setExpandedYaml] = useState(null);

  useEffect(() => {
    fetchPlugins();
  }, [fetchPlugins]);

  return (
    <div className={styles.page}>
      <h1 className={styles.pageTitle}>플러그인 관리</h1>

      {error && (
        <div style={{
          padding: '12px 16px', borderRadius: '8px', marginBottom: '16px',
          background: 'rgba(248,113,113,0.15)', color: 'var(--red)',
          fontSize: 'var(--fs-sm)',
        }}>
          {error}
        </div>
      )}

      {loading && plugins.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)' }}>
          플러그인 로딩 중...
        </div>
      ) : plugins.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)' }}>
          등록된 플러그인이 없습니다
        </div>
      ) : (
        <div className={styles.grid}>
          {plugins.map((plugin) => (
            <div key={plugin.id} className={styles.card}>
              <div className={styles.cardHeader}>
                <span className={styles.pluginName}>{plugin.name}</span>
                <span className={styles.version}>v{plugin.version}</span>
              </div>

              <p className={styles.description}>{plugin.description}</p>

              <div className={styles.meta}>
                <span className={styles.author}>
                  {plugin.category && <span style={{ marginRight: '8px', opacity: 0.7 }}>[{plugin.category}]</span>}
                  by {plugin.author || 'WalletSavior'}
                </span>
                <span
                  className={
                    plugin.status === 'active'
                      ? styles.statusActive
                      : styles.statusInactive
                  }
                >
                  {plugin.status === 'active' ? '● 활성' : '○ 비활성'}
                </span>
              </div>

              {/* 실제 메타데이터 */}
              {(plugin.target_url || plugin.strategy || plugin.schedule_cron) && (
                <div style={{
                  fontSize: '12px', color: 'var(--text3)', marginTop: '8px',
                  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px',
                }}>
                  {plugin.target_url && (
                    <>
                      <span>대상 URL:</span>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{plugin.target_url}</span>
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
                      <span>{'⭐'.repeat(Math.min(plugin.difficulty, 5))}</span>
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
                  className={
                    plugin.status === 'active' ? styles.toggleOn : styles.toggle
                  }
                  onClick={() => togglePlugin(plugin.id)}
                  aria-label={
                    plugin.status === 'active' ? '비활성화' : '활성화'
                  }
                />
              </div>

              <button
                className={styles.yamlToggle}
                onClick={() =>
                  setExpandedYaml(
                    expandedYaml === plugin.id ? null : plugin.id
                  )
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

              {expandedYaml === plugin.id && (
                <div className={styles.yamlViewer}>
                  <code className={styles.yamlCode}>{plugin.config}</code>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
