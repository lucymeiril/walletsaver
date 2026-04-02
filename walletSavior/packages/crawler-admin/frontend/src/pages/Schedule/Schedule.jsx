import { useState, useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { Play, Edit3 } from 'lucide-react';
import styles from './Schedule.module.css';

const CRON_PRESETS = {
  '*/5 * * * *': '매 5분마다',
  '*/10 * * * *': '매 10분마다',
  '*/30 * * * *': '매 30분마다',
  '0 * * * *': '매 시간',
  '0 */2 * * *': '매 2시간마다',
  '0 */3 * * *': '매 3시간마다',
  '0 */6 * * *': '매 6시간마다',
  '0 0 * * *': '매일 자정',
  '0 0 */6 * *': '매 6시간마다',
  '0 7 * * *': '매일 오전 7시',
};

function cronToHuman(cron) {
  return CRON_PRESETS[cron] || cron;
}

export default function Schedule() {
  const schedules = useAdminStore((s) => s.schedules);
  const toggleSchedule = useAdminStore((s) => s.toggleSchedule);
  const updateScheduleCron = useAdminStore((s) => s.updateScheduleCron);
  const fetchSchedules = useAdminStore((s) => s.fetchSchedules);
  const updateScheduleApi = useAdminStore((s) => s.updateScheduleApi);
  const loading = useAdminStore((s) => s.loading);
  const error = useAdminStore((s) => s.error);

  const [editing, setEditing] = useState(null);
  const [editCron, setEditCron] = useState('');

  useEffect(() => {
    fetchSchedules();
  }, [fetchSchedules]);

  const formatDateTime = (iso) => {
    if (!iso) return '-';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '-';
    return d.toLocaleString('ko-KR', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const handleEdit = (schedule) => {
    setEditing(schedule);
    setEditCron(schedule.cron);
  };

  const handleSave = () => {
    if (editing) {
      updateScheduleCron(editing.id, editCron, cronToHuman(editCron));
      updateScheduleApi(editing.crawlerId || editing.crawlerName, { cron: editCron, description: cronToHuman(editCron) });
      setEditing(null);
    }
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.pageTitle}>스케줄 관리</h1>

      {error && (
        <div style={{
          padding: '12px 16px', borderRadius: '8px', marginBottom: '16px',
          background: 'rgba(248,113,113,0.15)', color: 'var(--red)',
          fontSize: 'var(--fs-sm)',
        }}>
          {error}
        </div>
      )}

      {loading && schedules.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)' }}>
          스케줄 로딩 중...
        </div>
      ) : schedules.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)' }}>
          등록된 스케줄이 없습니다. 크롤러에서 스케줄을 설정하세요.
        </div>
      ) : (
        <div className={styles.tableCard}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>크롤러</th>
                <th>Cron 표현식</th>
                <th>다음 실행</th>
                <th>상태</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((schedule) => (
                <tr key={schedule.id}>
                  <td>
                    <span className={styles.crawlerName}>
                      {schedule.crawlerName}
                    </span>
                  </td>
                  <td>
                    <code className={styles.cronCode}>{schedule.cron}</code>
                    <div className={styles.cronDescription}>
                      {schedule.description || cronToHuman(schedule.cron)}
                    </div>
                  </td>
                  <td>
                    <span className={styles.nextRun}>
                      {formatDateTime(schedule.nextRun)}
                    </span>
                  </td>
                  <td>
                    <button
                      className={
                        schedule.enabled ? styles.toggleOn : styles.toggle
                      }
                      onClick={() => toggleSchedule(schedule.id)}
                      aria-label={schedule.enabled ? '비활성화' : '활성화'}
                    />
                  </td>
                  <td>
                    <div className={styles.actionsCell}>
                      <button
                        className={styles.actionBtn}
                        onClick={() => handleEdit(schedule)}
                      >
                        <Edit3 size={14} />
                        편집
                      </button>
                      <button className={styles.actionBtn}>
                        <Play size={14} />
                        실행
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Edit Modal */}
      {editing && (
        <div
          className={styles.editOverlay}
          onClick={(e) =>
            e.target === e.currentTarget && setEditing(null)
          }
        >
          <div className={styles.editModal}>
            <h3 className={styles.editTitle}>
              스케줄 편집 — {editing.crawlerName}
            </h3>

            <div className={styles.editField}>
              <label className={styles.editLabel}>Cron 표현식</label>
              <input
                className={styles.editInput}
                type="text"
                value={editCron}
                onChange={(e) => setEditCron(e.target.value)}
                placeholder="* * * * *"
              />
              <div className={styles.editPreview}>
                미리보기: {cronToHuman(editCron)}
              </div>
            </div>

            <div className={styles.editActions}>
              <button
                className={styles.cancelBtn}
                onClick={() => setEditing(null)}
              >
                취소
              </button>
              <button className={styles.saveBtn} onClick={handleSave}>
                저장
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
