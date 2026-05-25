import { AlertTriangle } from 'lucide-react';
import s from './ImportConflictList.module.css';

export default function ImportConflictList({ count = 0, mode = 'strict' }) {
  if (count === 0) return null;

  return (
    <div className={s.wrap} data-testid="conflict-box">
      <div className={s.header}>
        <AlertTriangle size={16} className={s.icon} />
        <span className={s.title}>충돌 항목 {count}건</span>
      </div>
      <p className={s.desc}>
        {mode === 'strict'
          ? '충돌 항목이 발견되었습니다. strict 모드에서는 충돌 시 적용이 거부됩니다. lenient 모드로 전환하면 기존 데이터를 유지한 채 나머지를 적용합니다.'
          : '충돌 항목이 발견되었습니다. lenient 모드에서는 충돌 항목을 스킵하고 나머지를 적용합니다.'}
      </p>
      <p className={s.hint}>충돌 상세 데이터는 서버 로그에서 확인하세요.</p>
    </div>
  );
}
