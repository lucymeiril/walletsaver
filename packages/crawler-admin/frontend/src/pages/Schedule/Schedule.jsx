import { useEffect, useState } from 'react';
import { Clock, Edit3, Play, Plus, Trash2, X } from 'lucide-react';

import { api } from '../../api/client';
import useAdminStore from '../../stores/adminStore';
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
      for (let i = min; i <= max; i += 1) values.add(i);
    } else if (trimmed.includes('/')) {
      const [range, step] = trimmed.split('/');
      const stepNum = Number.parseInt(step, 10);
      const start = range === '*' ? min : Number.parseInt(range, 10);
      if (!Number.isFinite(stepNum) || stepNum <= 0 || !Number.isFinite(start)) continue;
      for (let i = start; i <= max; i += stepNum) values.add(i);
    } else if (trimmed.includes('-')) {
      const [a, b] = trimmed.split('-').map(Number);
      if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
      for (let i = a; i <= b; i += 1) values.add(i);
    } else {
      const parsed = Number.parseInt(trimmed, 10);
      if (Number.isFinite(parsed)) values.add(parsed);
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
    const hours = [...hourSet].sort((a, b) => a - b);
    const minutes = [...minuteSet].sort((a, b) => a - b);
    const results = [];
    const now = new Date();
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    for (let dayIndex = 0; dayIndex < 400 && results.length < count; dayIndex += 1) {
      const monthMatch = monthSet.has(day.getMonth() + 1);
      const dayMatch = domSpecified && dowSpecified
        ? domSet.has(day.getDate()) || dowSet.has(day.getDay())
        : domSet.has(day.getDate()) && dowSet.has(day.getDay());

      if (monthMatch && dayMatch) {
        for (const hour of hours) {
          for (const minute of minutes) {
            if (results.length >= count) break;
            const candidate = new Date(
              day.getFullYear(),
              day.getMonth(),
              day.getDate(),
              hour,
              minute,
            );
            if (candidate > now) results.push(candidate);
          }
          if (results.length >= count) break;
        }
      }
      day.setDate(day.getDate() + 1);
    }
    return results;
  } catch {
    return [];
  }
}

function isValidCron(expr) {
  if (!expr || typeof expr !== 'string') return false;
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return false;
  const pattern = /^(\*|(\d+)([-/]\d+)?(,(\d+)([-/]\d+)?)*)$/;
  return parts.every((part) => pattern.test(part));
}

export default function Schedule() {
  const schedules = useAdminStore((state) => state.schedules);
  const toggleSchedule = useAdminStore((state) => state.toggleSchedule);
  const updateScheduleCron = useAdminStore((state) => state.updateScheduleCron);
  const fetchSchedules = useAdminStore((state) => state.fetchSchedules);
  const updateScheduleApi = useAdminStore((state) => state.updateScheduleApi);
  const createSchedule = useAdminStore((state) => state.createSchedule);
  const deleteScheduleApi = useAdminStore((state) => state.deleteScheduleApi);
  const loading = useAdminStore((state) => state.schedulesLoading);
  const error = useAdminStore((state) => state.schedulesError);

  const [plugins, setPlugins] = useState([]);
  const [pluginError, setPluginError] = useState('');
  const [editing, setEditing] = useState(null);
  const [editCron, setEditCron] = useState('');
  const [adding, setAdding] = useState(false);
  const [addCrawler, setAddCrawler] = useState('');
  const [addCron, setAddCron] = useState('0 7 * * *');
  const [deleting, setDeleting] = useState(null);
  const [runningId, setRunningId] = useState(null);
  const [cronError, setCronError] = useState('');

  useEffect(() => {
    fetchSchedules();
    api.getOrchestratorPlugins()
      .then((data) => {
        setPlugins(Array.isArray(data) ? data : data.plugins ?? []);
        setPluginError('');
      })
      .catch(() => {
        setPlugins([]);
        setPluginError('실행 가능한 크롤러 목록을 불러올 수 없습니다.');
      });
  }, [fetchSchedules]);

  const formatDateTime = (iso) => {
    if (!iso) return '-';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleString('ko-KR', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const handleEdit = (schedule) => {
    setEditing(schedule);
    setEditCron(schedule.cron);
    setCronError('');
  };

  const handleSave = async () => {
    if (!editing) return;
    if (!isValidCron(editCron)) {
      setCronError('올바른 Cron 표현식을 입력하세요 (예: 0 9 * * *)');
      return;
    }
    setCronError('');
    updateScheduleCron(editing.id, editCron, cronToHuman(editCron));
    const result = await updateScheduleApi(editing.id, {
      cron: editCron,
      description: cronToHuman(editCron),
    });
    if (result) setEditing(null);
  };

  const handleRunNow = async (schedule) => {
    setRunningId(schedule.id);
    try {
      await api.runScheduleNow(schedule.crawlerId);
      await fetchSchedules();
    } finally {
      setRunningId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    await deleteScheduleApi(deleting.id);
    setDeleting(null);
  };

  const handleAdd = async () => {
    if (!addCrawler || !addCron) return;
    if (!isValidCron(addCron)) {
      setCronError('올바른 Cron 표현식을 입력하세요 (예: 0 9 * * *)');
      return;
    }
    setCronError('');
    const result = await createSchedule({ crawler_name: addCrawler, cron: addCron });
    if (!result) return;
    setAdding(false);
    setAddCrawler('');
    setAddCron('0 7 * * *');
  };

  const scheduledPluginNames = new Set(schedules.map((schedule) => schedule.crawlerId));
  const availablePlugins = plugins.filter(
    (plugin) => !scheduledPluginNames.has(plugin.name),
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

      {(error || pluginError) && (
        <div style={{
          padding: '12px 16px',
          borderRadius: '8px',
          marginBottom: '16px',
          background: 'rgba(248,113,113,0.15)',
          color: 'var(--red)',
          fontSize: 'var(--fs-sm)',
        }}>
          {error || pluginError}
        </div>
      )}

      {loading && schedules.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)' }}>
          스케줄 로딩 중...
        </div>
      ) : schedules.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)' }}>
          등록된 스케줄이 없습니다.{' '}
          <button className={styles.inlineAddBtn} onClick={() => setAdding(true)}>
            스케줄을 추가
          </button>{' '}
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
                const nextRuns = getNextCronRuns(schedule.cron);
                return (
                  <tr key={schedule.id} className={!schedule.enabled ? styles.disabledRow : ''}>
                    <td>
                      <span className={styles.crawlerName}>{schedule.crawlerName}</span>
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
                          {formatDateTime(nextRuns[0]?.toISOString())}
                        </span>
                        {nextRuns.length > 1 && (
                          <div className={styles.nextRunsList}>
                            {nextRuns.slice(1).map((run, index) => (
                              <span key={index} className={styles.nextRunItem}>
                                <Clock size={10} />
                                {formatDateTime(run.toISOString())}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </td>
                    <td>
                      <button
                        className={schedule.enabled ? styles.toggleOn : styles.toggle}
                        onClick={() => toggleSchedule(schedule.id)}
                        aria-label={schedule.enabled ? '비활성화' : '활성화'}
                      />
                    </td>
                    <td>
                      <div className={styles.actionsCell}>
                        <button className={styles.actionBtn} onClick={() => handleEdit(schedule)}>
                          <Edit3 size={14} />
                          편집
                        </button>
                        <button
                          className={`${styles.actionBtn} ${runningId === schedule.id ? styles.runningBtn : ''}`}
                          onClick={() => handleRunNow(schedule)}
                          disabled={runningId === schedule.id}
                        >
                          <Play size={14} />
                          {runningId === schedule.id ? '실행 중...' : '실행'}
                        </button>
                        <button
                          className={`${styles.actionBtn} ${styles.deleteBtn}`}
                          onClick={() => setDeleting(schedule)}
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

      {editing && (
        <div
          className={styles.editOverlay}
          onClick={(event) => event.target === event.currentTarget && setEditing(null)}
        >
          <div className={styles.editModal}>
            <div className={styles.modalHeader}>
              <h3 className={styles.editTitle}>스케줄 편집 — {editing.crawlerName}</h3>
              <button className={styles.closeBtn} onClick={() => setEditing(null)}>
                <X size={18} />
              </button>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>프리셋 선택</label>
              <div className={styles.presetGrid}>
                {Object.entries(CRON_PRESETS).map(([cron, label]) => (
                  <button
                    key={cron}
                    className={`${styles.presetChip} ${editCron === cron ? styles.presetActive : ''}`}
                    onClick={() => setEditCron(cron)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>Cron 표현식 (직접 입력)</label>
              <input
                className={styles.editInput}
                type="text"
                value={editCron}
                onChange={(event) => setEditCron(event.target.value)}
                placeholder="0 9 * * *"
              />
              <div className={styles.editPreview}>미리보기: {cronToHuman(editCron)}</div>
              {cronError && (
                <div style={{ color: 'var(--red, #ef4444)', fontSize: '0.8rem', marginTop: '4px' }}>
                  {cronError}
                </div>
              )}
            </div>

            {editNextRuns.length > 0 && (
              <div className={styles.nextRunsPreview}>
                <label className={styles.editLabel}>다음 실행 예정</label>
                {editNextRuns.map((date, index) => (
                  <div key={index} className={styles.previewRunItem}>
                    <Clock size={12} />
                    {date.toLocaleString('ko-KR')}
                  </div>
                ))}
              </div>
            )}

            <div className={styles.editActions}>
              <button
                className={styles.cancelBtn}
                onClick={() => {
                  setEditing(null);
                  setCronError('');
                }}
              >
                취소
              </button>
              <button className={styles.saveBtn} onClick={handleSave}>저장</button>
            </div>
          </div>
        </div>
      )}

      {adding && (
        <div
          className={styles.editOverlay}
          onClick={(event) => event.target === event.currentTarget && setAdding(false)}
        >
          <div className={styles.editModal}>
            <div className={styles.modalHeader}>
              <h3 className={styles.editTitle}>스케줄 추가</h3>
              <button className={styles.closeBtn} onClick={() => setAdding(false)}>
                <X size={18} />
              </button>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>실행 대상 선택</label>
              <select
                className={styles.editSelect}
                value={addCrawler}
                onChange={(event) => setAddCrawler(event.target.value)}
              >
                <option value="">실행 대상을 선택하세요</option>
                {availablePlugins.map((plugin) => (
                  <option key={plugin.name} value={plugin.name}>
                    {plugin.display_name || plugin.name}
                  </option>
                ))}
                {availablePlugins.length === 0 && plugins.length > 0 && (
                  <option disabled>모든 실행 대상에 스케줄이 설정되어 있습니다</option>
                )}
              </select>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>프리셋 선택</label>
              <div className={styles.presetGrid}>
                {Object.entries(CRON_PRESETS).map(([cron, label]) => (
                  <button
                    key={cron}
                    className={`${styles.presetChip} ${addCron === cron ? styles.presetActive : ''}`}
                    onClick={() => setAddCron(cron)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className={styles.editField}>
              <label className={styles.editLabel}>Cron 표현식 (직접 입력)</label>
              <input
                className={styles.editInput}
                type="text"
                value={addCron}
                onChange={(event) => setAddCron(event.target.value)}
                placeholder="0 7 * * *"
              />
              <div className={styles.editPreview}>미리보기: {cronToHuman(addCron)}</div>
              {cronError && (
                <div style={{ color: 'var(--red, #ef4444)', fontSize: '0.8rem', marginTop: '4px' }}>
                  {cronError}
                </div>
              )}
            </div>

            {addNextRuns.length > 0 && (
              <div className={styles.nextRunsPreview}>
                <label className={styles.editLabel}>다음 실행 예정</label>
                {addNextRuns.map((date, index) => (
                  <div key={index} className={styles.previewRunItem}>
                    <Clock size={12} />
                    {date.toLocaleString('ko-KR')}
                  </div>
                ))}
              </div>
            )}

            <div className={styles.editActions}>
              <button
                className={styles.cancelBtn}
                onClick={() => {
                  setAdding(false);
                  setCronError('');
                }}
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

      {deleting && (
        <div
          className={styles.editOverlay}
          onClick={(event) => event.target === event.currentTarget && setDeleting(null)}
        >
          <div className={styles.confirmModal}>
            <h3 className={styles.editTitle}>스케줄 삭제</h3>
            <p className={styles.confirmText}>
              <strong>{deleting.crawlerName}</strong> 스케줄을 정말 삭제하시겠습니까?
              <br />
              이 작업은 되돌릴 수 없습니다.
            </p>
            <div className={styles.editActions}>
              <button className={styles.cancelBtn} onClick={() => setDeleting(null)}>
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
