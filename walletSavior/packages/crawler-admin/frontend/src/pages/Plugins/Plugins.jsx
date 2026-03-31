import { useState } from 'react';
import useAdminStore from '../../stores/adminStore';
import { Code, ChevronDown, ChevronUp } from 'lucide-react';
import styles from './Plugins.module.css';

export default function Plugins() {
  const plugins = useAdminStore((s) => s.plugins);
  const togglePlugin = useAdminStore((s) => s.togglePlugin);
  const [expandedYaml, setExpandedYaml] = useState(null);

  return (
    <div className={styles.page}>
      <h1 className={styles.pageTitle}>플러그인 관리</h1>

      <div className={styles.grid}>
        {plugins.map((plugin) => (
          <div key={plugin.id} className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.pluginName}>{plugin.name}</span>
              <span className={styles.version}>v{plugin.version}</span>
            </div>

            <p className={styles.description}>{plugin.description}</p>

            <div className={styles.meta}>
              <span className={styles.author}>by {plugin.author}</span>
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
    </div>
  );
}
