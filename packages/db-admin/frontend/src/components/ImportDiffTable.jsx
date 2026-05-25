import s from './ImportDiffTable.module.css';

const ACTION_LABEL = { add: '추가', update: '수정' };
const ACTION_CLASS = { add: s.badgeAdd, update: s.badgeUpdate };

export default function ImportDiffTable({ rows = [], maxRows = 20 }) {
  const visible = rows.slice(0, maxRows);

  if (!visible.length) {
    return <p className={s.empty}>미리보기할 행이 없습니다.</p>;
  }

  return (
    <div className={s.wrap}>
      <table className={s.table}>
        <thead>
          <tr>
            <th>동작</th>
            <th>match_key</th>
            <th>category_id</th>
            <th>confidence</th>
            <th>source</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((row, i) => (
            <tr key={i} className={row.action === 'update' ? s.rowUpdate : s.rowAdd}>
              <td>
                <span className={`${s.badge} ${ACTION_CLASS[row.action] ?? ''}`}>
                  {ACTION_LABEL[row.action] ?? row.action}
                </span>
              </td>
              <td className={s.mono}>{row.match_key ?? '—'}</td>
              <td>{row.category_id ?? '—'}</td>
              <td>{row.confidence != null ? Number(row.confidence).toFixed(3) : '—'}</td>
              <td>{row.source ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && (
        <p className={s.more}>… 외 {rows.length - maxRows}행 (총 {rows.length}행)</p>
      )}
    </div>
  );
}
