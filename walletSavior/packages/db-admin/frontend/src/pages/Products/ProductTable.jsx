import { Pencil, Trash2, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, ArrowUpDown } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import s from './Products.module.css';

const SOURCE_LABELS = {
  all: '전체', emart: '이마트', homeplus: '홈플러스',
  lottemart: '롯데마트', costco: '코스트코', hotdeal: '핫딜', government: '정부데이터',
};

function SortIcon({ col, sortBy, sortDir }) {
  if (sortBy !== col) return <ArrowUpDown size={12} className={s.sortIconInactive} />;
  return sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />;
}

function ProductRow({ p, selected, onToggleSelect, expanded, onToggleExpand, rowHistory, onDetail, onEdit, onDelete }) {
  return (
    <>
      <tr className={`${s.row} ${selected ? s.rowSelected : ''}`}>
        <td className={s.checkCol} onClick={e => e.stopPropagation()}>
          <input type="checkbox" checked={selected} onChange={onToggleSelect} />
        </td>
        <td className={s.nameCol} onClick={onDetail}>
          <div className={s.nameWrap}>
            {p.image_url && <img src={p.image_url} alt="" className={s.thumbImg} />}
            <span>{p.name}</span>
          </div>
        </td>
        <td onClick={onDetail}>{p.category}</td>
        <td onClick={onDetail}>{p.unit}</td>
        <td onClick={onDetail}>{p.currentPrice ? `${p.currentPrice.toLocaleString()}원` : '-'}</td>
        <td onClick={onDetail}>{p.originalPrice ? `${p.originalPrice.toLocaleString()}원` : '-'}</td>
        <td onClick={onDetail}>
          {p.discountRate ? (
            <span className={s.discountBadge}>{p.discountRate.toFixed(1)}%</span>
          ) : '-'}
        </td>
        <td onClick={onDetail}>
          <div className={s.sourceTags}>
            {(p.sources || (p.source ? [p.source] : [])).map(src => (
              <span key={src} className={s.sourceTag}>{SOURCE_LABELS[src] || src}</span>
            ))}
          </div>
        </td>
        <td>
          <div className={s.actions} onClick={e => e.stopPropagation()}>
            <button className={s.iconBtn} onClick={onToggleExpand} title="가격 이력">
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            <button className={s.iconBtn} onClick={onEdit} title="수정"><Pencil size={14} /></button>
            <button className={s.iconBtn} onClick={onDelete} title="삭제"><Trash2 size={14} /></button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className={s.expandedRow}>
          <td colSpan={9}>
            <div className={s.expandedContent}>
              <h4 className={s.expandTitle}>가격 이력 (30일)</h4>
              {rowHistory && rowHistory.length > 0 ? (
                <div style={{ height: 160 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={rowHistory.slice(-30)}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="date" tick={{ fill: 'var(--text3)', fontSize: 10 }} tickFormatter={v => String(v).slice(5)} />
                      <YAxis tick={{ fill: 'var(--text3)', fontSize: 10 }} />
                      <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
                      <Line type="monotone" dataKey="price" stroke="var(--accent)" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className={s.noData}>{rowHistory === null ? '불러오는 중...' : '가격 이력이 없습니다.'}</p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function ProductTable({
  products, selected, onToggleSelect, onToggleSelectAll,
  expandedRow, onToggleExpand, rowHistory,
  sortBy, sortDir, onToggleSort,
  onDetail, onEdit, onDelete,
  page, setPage, total, totalPages,
}) {
  const allOnPageSelected = products.length > 0 && products.every(p => selected.has(p.id));

  return (
    <>
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead>
            <tr>
              <th className={s.checkCol}>
                <input type="checkbox" checked={allOnPageSelected} onChange={onToggleSelectAll} />
              </th>
              <th className={s.sortableCol} onClick={() => onToggleSort('name')}>
                이름 <SortIcon col="name" sortBy={sortBy} sortDir={sortDir} />
              </th>
              <th>카테고리</th>
              <th>단위</th>
              <th className={s.sortableCol} onClick={() => onToggleSort('price')}>
                현재가 <SortIcon col="price" sortBy={sortBy} sortDir={sortDir} />
              </th>
              <th>원래가</th>
              <th className={s.sortableCol} onClick={() => onToggleSort('discount_rate')}>
                할인율 <SortIcon col="discount_rate" sortBy={sortBy} sortDir={sortDir} />
              </th>
              <th>소스</th>
              <th>관리</th>
            </tr>
          </thead>
          <tbody>
            {products.map(p => (
              <ProductRow
                key={p.id}
                p={p}
                selected={selected.has(p.id)}
                onToggleSelect={() => onToggleSelect(p.id)}
                expanded={expandedRow === p.id}
                onToggleExpand={() => onToggleExpand(p.id)}
                rowHistory={expandedRow === p.id ? rowHistory : null}
                onDetail={() => onDetail(p)}
                onEdit={() => onEdit(p)}
                onDelete={() => onDelete(p.id)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* 페이지네이션 */}
      <div className={s.pagination}>
        <span className={s.count}>총 {total.toLocaleString()}개 상품</span>
        <div className={s.pageControls}>
          <button className={s.pageBtn} disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
            <ChevronLeft size={16} />
          </button>
          <span className={s.pageInfo}>{page} / {totalPages}</span>
          <button className={s.pageBtn} disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </>
  );
}
