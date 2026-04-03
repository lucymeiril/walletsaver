import { useState, useEffect } from 'react';
import { Search, Trash2, Package } from 'lucide-react';
import { api } from '../../api/client';
import s from './Products.module.css';

const DEFAULT_SOURCE_LABELS = {
  emart: '이마트', homeplus: '홈플러스',
  lottemart: '롯데마트', costco: '코스트코', hotdeal: '핫딜', government: '정부데이터',
  musinsa: '무신사', giordano: '지오다노', community: '커뮤니티',
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
  const [dynamicSources, setDynamicSources] = useState([]);

  useEffect(() => {
    api.getSourceTypes()
      .then(data => { if (Array.isArray(data)) setDynamicSources(data); })
      .catch(() => {});
  }, []);

  const sourceEntries = [['all', '전체']];
  const seen = new Set(['all']);

  // DB에서 가져온 동적 소스 우선
  for (const src of dynamicSources) {
    if (!seen.has(src)) {
      seen.add(src);
      sourceEntries.push([src, DEFAULT_SOURCE_LABELS[src] || src]);
    }
  }

  // stats.by_source의 키도 추가 (DB 소스 타입 API 실패 시 폴백)
  if (stats?.by_source) {
    for (const src of Object.keys(stats.by_source)) {
      if (!seen.has(src)) {
        seen.add(src);
        sourceEntries.push([src, DEFAULT_SOURCE_LABELS[src] || src]);
      }
    }
  }

  const handleSearchKey = (e) => {
    if (e.key === 'Enter') onSearch();
  };

  return (
    <>
      {/* 소스 필터 탭 */}
      <div className={s.sourceTabs}>
        {sourceEntries.map(([key, label]) => (
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
