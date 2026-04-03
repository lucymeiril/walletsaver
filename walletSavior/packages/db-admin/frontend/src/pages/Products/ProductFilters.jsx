import { Search, Trash2, Package } from 'lucide-react';
import s from './Products.module.css';

const SOURCE_LABELS = {
  all: '전체', emart: '이마트', homeplus: '홈플러스',
  lottemart: '롯데마트', costco: '코스트코', hotdeal: '핫딜', government: '정부데이터',
};

const SORT_OPTIONS = [
  { value: 'name', label: '이름순' },
  { value: 'price', label: '가격순' },
  { value: 'discount_rate', label: '할인율순' },
  { value: 'created_at', label: '등록일순' },
];

export default function ProductFilters({
  sourceFilter, setSourceFilter,
  catFilter, setCatFilter,
  search, setSearch,
  sortBy, setSortBy,
  sortDir, setSortDir,
  setPage,
  onSearch,
  stats,
  selected,
  onBulkDelete,
  onBulkCategoryOpen,
  onClearSelection,
}) {
  const handleSearchKey = (e) => {
    if (e.key === 'Enter') onSearch();
  };

  return (
    <>
      {/* 소스 필터 탭 */}
      <div className={s.sourceTabs}>
        {Object.entries(SOURCE_LABELS).map(([key, label]) => (
          <button
            key={key}
            className={`${s.sourceTab} ${sourceFilter === key ? s.sourceTabActive : ''}`}
            onClick={() => { setSourceFilter(key); setPage(1); }}
          >
            {label}
            {key !== 'all' && stats?.by_source?.[key] != null && (
              <span className={s.tabBadge}>{stats.by_source[key]}</span>
            )}
            {key === 'all' && stats && (
              <span className={s.tabBadge}>{stats.total ?? 0}</span>
            )}
          </button>
        ))}
      </div>

      {/* 필터 / 검색 / 정렬 */}
      <div className={s.filters}>
        <div className={s.searchWrap}>
          <Search size={16} className={s.searchIcon} />
          <input
            className={s.searchInput}
            placeholder="상품명 검색..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={handleSearchKey}
          />
          <button className={s.searchBtn} onClick={onSearch}>검색</button>
        </div>
        <select className={s.select} value={catFilter} onChange={e => { setCatFilter(e.target.value); setPage(1); }}>
          <option value="">전체 카테고리</option>
          {(stats?.by_category || []).map(c => (
            <option key={c.name} value={c.name}>{c.name} ({c.count})</option>
          ))}
        </select>
        <select className={s.select} value={`${sortBy}-${sortDir}`} onChange={e => {
          const [sb, sd] = e.target.value.split('-');
          setSortBy(sb); setSortDir(sd); setPage(1);
        }}>
          {SORT_OPTIONS.map(opt => (
            <optgroup key={opt.value} label={opt.label}>
              <option value={`${opt.value}-asc`}>{opt.label} ↑</option>
              <option value={`${opt.value}-desc`}>{opt.label} ↓</option>
            </optgroup>
          ))}
        </select>
      </div>

      {/* 벌크 액션 바 */}
      {selected.size > 0 && (
        <div className={s.bulkBar}>
          <span className={s.bulkCount}>{selected.size}개 선택됨</span>
          <button className={s.bulkBtn} onClick={onBulkDelete}>
            <Trash2 size={14} /> 일괄 삭제
          </button>
          <button className={s.bulkBtn} onClick={onBulkCategoryOpen}>
            <Package size={14} /> 카테고리 변경
          </button>
          <button className={s.bulkCancelBtn} onClick={onClearSelection}>선택 해제</button>
        </div>
      )}
    </>
  );
}
