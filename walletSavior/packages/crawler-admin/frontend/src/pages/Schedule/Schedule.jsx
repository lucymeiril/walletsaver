import { useState, useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { api } from '../../api/client';
import { Play, Edit3, Trash2, Plus, X, Clock } from 'lucide-react';
import styles from './Schedule.module.css';

const CRON_PRESETS = {
  '*/5 * * * *': '매 5분마다',
  '*/10 * * * *': '매 10분마다',
  '*/30 * * * *': '매 30분마다',
  '0 * * * *': '매 시간',
  '0 */2 * * *': '매 2시간마다',
  '0 */3 * * *': '매 3시간마다',
  '0 */6 * * *': '매 6시간마다',
  '0 */12 * * *': '매 12시간마다',
  '0 0 * * *': '매일 자정',
  '0 7 * * *': '매일 오전 7시',
  '0 9 * * *': '매일 오전 9시',
  '0 12 * * *': '매일 정오',
  '0 19 * * *': '매일 오후 7시',
  '0 7 * * 1': '매주 월요일 오전 7시',
  '0 7 * * 1-5': '평일 오전 7시',
  '0 0 * * 0': '매주 일요일 자정',
  '0 0 1 * *': '매월 1일 자정',
};

function cronToHuman(cron) {
  return CRON_PRESETS[cron] || cron;
}

function parseCronField(field, min, max) {
  const values = new Set();
  for (const part of field.split(',')) {
    const trimmed = part.trim();
    if (trimmed === '*') {
      for (let i = min; i <= max; i++) values.add(i);
    } else if (trimmed.includes('/')) {
      const [range, step] = trimmed.split('/');
      const stepNum = parseInt(step);
      const start = range === '*' ? min : parseInt(range);
      for (let i = start; i <= max; i += stepNum) values.add(i);
    } else if (trimmed.includes('-')) {
      const [a, b] = trimmed.split('-').map(Number);
      for (let i = a; i <= b; i++) values.add(i);
    } else {
      values.add(parseInt(trimmed));
    }
  }
  return values;
}

function getNextCronRuns(cronExpr, count = 3) {
  try {
    const parts = cronExpr.trim().split(/\s+/);
    if (parts.length !== 5) return [];

    const minuteSet = parseCronField(parts[0], 0, 59);
    const hourSet = parseCronField(parts[1], 0, 23);
    const domSet = parseCronField(parts[2], 1, 31);
    const monthSet = parseCronField(parts[3], 1, 12);
    const dowSet = parseCronField(parts[4], 0, 6);

    const domSpecified = parts[2] !== '*';
    const dowSpecified = parts[4] !== '*';
    const hourArr = [...hourSet].sort((a, b) => a - b);
    const minuteArr = [...minuteSet].sort((a, b) => a - b);

    const results = [];
    const now = new Date();
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    for (let dayIdx = 0; dayIdx < 400 && results.length < count; dayIdx++) {
      const monthMatch = monthSet.has(d.getMonth() + 1);
      let dayMatch;
      if (domSpecified && dowSpecified) {
        dayMatch = domSet.has(d.getDate()) || dowSet.has(d.getDay());
      } else {
        dayMatch = domSet.has(d.getDate()) && dowSet.has(d.getDay());
      }

      if (monthMatch && dayMatch) {
        for (const h of hourArr) {
          if (results.length >= count) break;
          for (const m of minuteArr) {
            if (results.length >= count) break;
            const candidate = new Date(
              d.getFullYear(), d.getMonth(), d.getDate(), h, m
            );
            if (candidate > now) {
              results.push(candidate);
            }
          }
        }
      }
      d.setDate(d.getDate() + 1);
    }

    return results;
  } catch {
    return [];
  }
}

export default function Schedule() {
  const schedules = useAdminStore((s) => s.schedules);
  const crawlers = useAdminStore((s) => s.crawlers);
  const toggleSchedule = useAdminStore((s) => s.toggleSchedule);
  const updateScheduleCron = useAdminStore((s) => s.updateScheduleCron);
  const fetchSchedules = useAdminStore((s) => s.fetchSchedules);
  const fetchCrawlers = useAdminStore((s) => s.fetchCrawlers);
  const updateScheduleApi = useAdminStore((s) => s.updateScheduleApi);
  const createSchedule = useAdminStore((s) => s.createSchedule);
  const deleteScheduleApi = useAdminStore((s) => s.deleteScheduleApi);
  const loading = useAdminStore((s) => s.loading);
  const error = useAdminStore((s) => s.error);

  const [editing, setEditing] = useState(null);
  const [editCron, setEditCron] = useState('');
  const [adding, setAdding] = useState(false);
  const [addCrawler, setAddCrawler] = useState('');
  const [addCron, setAddCron] = useState('0 7 * * *');
  const [deleting, setDeleting] = useState(null);
  const [runningId, setRunningId] = useState(null);

  useEffect(() => {
    fetchSchedules();
    fetchCrawlers();
  }, [fetchSchedules, fetchCrawlers]);

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
      updateScheduleApi(editing.crawlerId || editing.crawlerName, {
        cron: editCron,
        description: cronToHuman(editCron),
      });
      setEditing(null);
    }
  };

  const handleRunNow = async (schedule) => {
    const name = schedule.crawlerId || schedule.crawlerName;
    setRunningId(schedule.id);
    try {
      await api.runScheduleNow(name);
    } catch {
      // 실행 요청 실패 시 무시 (UI 피드백은 runningId 상태로 대체)
    } finally {
      setTimeout(() => setRunningId(null), 2000);
    }
  };

  const handleDeleteClick = (schedule) => {
    setDeleting(schedule);
  };

  const confirmDelete = () => {
    if (deleting) {
      deleteScheduleApi(deleting.crawlerId || deleting.crawlerName);
      setDeleting(null);
    }
  };

  const handleAdd = () => {
    if (addCrawler && addCron) {
      createSchedule({ crawler_name: addCrawler, cron: addCron });
      setAdding(false);
      setAddCrawler('');
      setAddCron('0 7 * * *');
    }
  };

  const scheduledCrawlerNames = new Set(
    schedules.map((s) => s.crawlerId || s.crawlerName)
  );
  const availableCrawlers = crawlers.filter(
    (c) => !scheduledCrawlerNames.has(c.id)
  );

  const editNextRuns = getNextCronRuns(editCron);
  const addNextRuns = getNextCronRuns(addCron);

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>스케줄 관리</h1>
        <button className={styles.addBtn} onClick={() => setAdding(true)}>
          <Plus size={16} />
          스케줄 추가
        </button>
      </div>

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
          등록된 스케줄이 없습니다.{' '}
          <button
            className={styles.inlineAddBtn}
            onClick={() => setAdding(true)}
          >
            스케줄을 추가
          </button>
          하세요.
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
              {schedules.map((schedule) => {
                const nextRuns = schedule.nextRuns || [];
                return (
                  <tr
                    key={schedule.id}
                    className={!schedule.enabled ? styles.disabledRow : ''}
                  >
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
                      <div className={styles.nextRunCell}>
                        <span className={styles.nextRun}>
                          {formatDateTime(schedule.nextRun)}
                        </span>
                        {nextRuns.length > 1 && (
                          <div className={styles.nextRunsList}>
                            {nextRuns.slice(1).map((run, i) => (
                              <span key={i} className={styles.nextRunItem}>
                                <Clock size={10} />
                                {formatDateTime(run)}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
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
                        <button
                          className={`${styles.actionBtn} ${
                            runningId === schedule.id ? styles.runningBtn : ''
                          }`}
                          onClick={() => handleRunNow(schedule)}
                          disabled={runningId === schedule.id}
                        >
                          <Play size={14} />
                          {runningId === schedule.id ? '실행 중...' : '실행'}
                        </button>
                        <button
                          className={`${styles.actionBtn} ${styles.deleteBtn}`}
                          onClick={() => handleDeleteClick(schedule)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
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
            <div className={styles.modalHeader}>
              <h3 className={styles.editTitle}>
                스케줄 편집 — {editing.crawlerName}
              </h3>
              <button
                className={styles.closeBtn}
                onClick={() => setEditing(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>프리셋 선택</label>
              <div className={styles.presetGrid}>
                {Object.entries(CRON_PRESETS).map(([cron, label]) => (
                  <button
                    key={cron}
                    className={`${styles.presetChip} ${
                      editCron === cron ? styles.presetActive : ''
                    }`}
                    onClick={() => setEditCron(cron)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>
                Cron 표현식 (직접 입력)
              </label>
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

            {editNextRuns.length > 0 && (
              <div className={styles.nextRunsPreview}>
                <label className={styles.editLabel}>다음 실행 예정</label>
                {editNextRuns.map((d, i) => (
                  <div key={i} className={styles.previewRunItem}>
                    <Clock size={12} />
                    {d.toLocaleString('ko-KR', {
                      year: 'numeric',
                      month: 'long',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                      weekday: 'short',
                    })}
                  </div>
                ))}
              </div>
            )}

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

      {/* Add Schedule Modal */}
      {adding && (
        <div
          className={styles.editOverlay}
          onClick={(e) =>
            e.target === e.currentTarget && setAdding(false)
          }
        >
          <div className={styles.editModal}>
            <div className={styles.modalHeader}>
              <h3 className={styles.editTitle}>스케줄 추가</h3>
              <button
                className={styles.closeBtn}
                onClick={() => setAdding(false)}
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>크롤러 선택</label>
              <select
                className={styles.editSelect}
                value={addCrawler}
                onChange={(e) => setAddCrawler(e.target.value)}
              >
                <option value="">크롤러를 선택하세요</option>
                {availableCrawlers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
                {availableCrawlers.length === 0 && crawlers.length > 0 && (
                  <option disabled>
                    모든 크롤러에 스케줄이 설정되어 있습니다
                  </option>
                )}
              </select>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>프리셋 선택</label>
              <div className={styles.presetGrid}>
                {Object.entries(CRON_PRESETS).map(([cron, label]) => (
                  <button
                    key={cron}
                    className={`${styles.presetChip} ${
                      addCron === cron ? styles.presetActive : ''
                    }`}
                    onClick={() => setAddCron(cron)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>
                Cron 표현식 (직접 입력)
              </label>
              <input
                className={styles.editInput}
                type="text"
                value={addCron}
                onChange={(e) => setAddCron(e.target.value)}
                placeholder="* * * * *"
              />
              <div className={styles.editPreview}>
                미리보기: {cronToHuman(addCron)}
              </div>
            </div>

            {addNextRuns.length > 0 && (
              <div className={styles.nextRunsPreview}>
                <label className={styles.editLabel}>다음 실행 예정</label>
                {addNextRuns.map((d, i) => (
                  <div key={i} className={styles.previewRunItem}>
                    <Clock size={12} />
                    {d.toLocaleString('ko-KR', {
                      year: 'numeric',
                      month: 'long',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                      weekday: 'short',
                    })}
                  </div>
                ))}
              </div>
            )}

            <div className={styles.editActions}>
              <button
                className={styles.cancelBtn}
                onClick={() => setAdding(false)}
              >
                취소
              </button>
              <button
                className={styles.saveBtn}
                onClick={handleAdd}
                disabled={!addCrawler || !addCron}
              >
                추가
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {deleting && (
        <div
          className={styles.editOverlay}
          onClick={(e) =>
            e.target === e.currentTarget && setDeleting(null)
          }
        >
          <div className={styles.confirmModal}>
            <h3 className={styles.editTitle}>스케줄 삭제</h3>
            <p className={styles.confirmText}>
              <strong>{deleting.crawlerName}</strong> 스케줄을 정말
              삭제하시겠습니까?
              <br />
              이 작업은 되돌릴 수 없습니다.
            </p>
            <div className={styles.editActions}>
              <button
                className={styles.cancelBtn}
                onClick={() => setDeleting(null)}
              >
                취소
              </button>
              <button className={styles.dangerBtn} onClick={confirmDelete}>
                삭제
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
