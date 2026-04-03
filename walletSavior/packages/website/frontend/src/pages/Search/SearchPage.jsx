import { useState, useEffect, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Search, ShoppingBag, Zap, Users, MapPin } from 'lucide-react';
import { searchService } from '../../services/searchService';
import useStore from '../../stores/appStore';
import Tabs from '../../components/common/Tabs';
import Spinner from '../../components/common/Spinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorFallback from '../../components/common/ErrorFallback';
import Card from '../../components/common/Card';
import SearchAutocomplete from '../../components/search/SearchAutocomplete';
import s from './SearchPage.module.css';

const TABS = [
  { id: 'all',     label: '전체' },
  { id: 'product', label: '상품' },
  { id: 'hotdeal', label: '핫딜' },
  { id: 'post',    label: '커뮤니티' },
  { id: 'mart',    label: '동네' },
];

const TYPE_META = {
  product: { icon: ShoppingBag, badge: '상품',    color: 'var(--accent)' },
  hotdeal: { icon: Zap,         badge: '핫딜',    color: 'var(--red, #ef4444)' },
  post:    { icon: Users,       badge: '커뮤니티', color: 'var(--green, #22c55e)' },
  mart:    { icon: MapPin,      badge: '동네',    color: 'var(--orange, #f59e0b)' },
};

const SORT_OPTIONS = [
  { value: 'relevant', label: '관련순' },
  { value: 'recent',   label: '최신순' },
  { value: 'popular',  label: '인기순' },
];

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const query = searchParams.get('q') || '';
  const activeType = searchParams.get('type') || 'all';
  const sort = searchParams.get('sort') || 'relevant';

  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null);

  const addRecentSearch = useStore((st) => st.addRecentSearch);

  const fetchResults = useCallback(async () => {
    if (!query) return;
    setLoading(true);
    setError(null);
    try {
      const params = { sort };
      if (activeType !== 'all') params.type = activeType;
      const res = await searchService.search(query, params);
      setResults(res.data || []);
      setMeta(res.meta || null);
    } catch (err) {
      setError(err);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, activeType, sort]);

  useEffect(() => {
    fetchResults();
    if (query) addRecentSearch(query);
  }, [fetchResults]);

  const handleTabChange = (tabId) => {
    const params = new URLSearchParams(searchParams);
    if (tabId === 'all') params.delete('type');
    else params.set('type', tabId);
    setSearchParams(params);
  };

  const handleSortChange = (e) => {
    const params = new URLSearchParams(searchParams);
    params.set('sort', e.target.value);
    setSearchParams(params);
  };

  const handleSearchSubmit = (q) => {
    const params = new URLSearchParams(searchParams);
    params.set('q', q);
    setSearchParams(params);
  };

  const handleItemClick = (item) => {
    if (item.type === 'product') navigate(`/price/${item.id}`);
    else if (item.type === 'hotdeal') navigate('/hotdeal');
    else if (item.type === 'post') navigate('/community');
    else if (item.type === 'mart') navigate('/mart');
  };

  const categorized = {};
  for (const tab of TABS) {
    if (tab.id === 'all') continue;
    categorized[tab.id] = results.filter((r) => r.type === tab.id);
  }

  const tabs = TABS.map((tab) => {
    const count = tab.id === 'all' ? results.length : (categorized[tab.id]?.length || 0);
    return {
      ...tab,
      label: `${tab.label} (${count})`,
      content: null,
    };
  });

  const displayResults = activeType === 'all' ? results : (categorized[activeType] || []);

  return (
    <div className={s.page}>
      <div className={s.container}>
        <SearchAutocomplete
          variant="page"
          placeholder="상품, 핫딜, 커뮤니티 검색..."
          initialValue={query}
          onSearch={handleSearchSubmit}
          className={s.searchForm}
        />

        {query && (
          <>
            <div className={s.toolbar}>
              <h2 className={s.queryTitle}>
                &lsquo;<strong>{query}</strong>&rsquo; 검색 결과
              </h2>
              <select className={s.sortSelect} value={sort} onChange={handleSortChange}>
                {SORT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            <Tabs
              tabs={tabs}
              defaultTab={activeType}
              onChange={handleTabChange}
            />

            {loading && (
              <div className={s.center}><Spinner /></div>
            )}

            {error && !loading && (
              <ErrorFallback error={error} onRetry={fetchResults} />
            )}

            {!loading && !error && displayResults.length === 0 && (
              <EmptyState
                icon={Search}
                title="검색 결과가 없습니다"
                description={`'${query}'에 대한 ${activeType === 'all' ? '' : TABS.find(t => t.id === activeType)?.label.split(' ')[0] + ' '}결과가 없습니다.`}
              />
            )}

            {!loading && !error && displayResults.length > 0 && (
              <div className={s.resultList}>
                {displayResults.map((item, i) => {
                  const meta = TYPE_META[item.type] || TYPE_META.product;
                  const Icon = meta.icon;
                  return (
                    <Card key={`${item.type}-${item.id}-${i}`} variant="interactive" onClick={() => handleItemClick(item)}>
                      <div className={s.resultItem}>
                        {item.image && (
                          <img src={item.image} alt="" className={s.thumb} loading="lazy" />
                        )}
                        <div className={s.resultBody}>
                          <div className={s.resultTop}>
                            <span className={s.typeBadge} style={{ background: meta.color }}>
                              <Icon size={12} />
                              {meta.badge}
                            </span>
                            <h3 className={s.resultTitle}>{item.title}</h3>
                          </div>
                          {item.description && (
                            <p className={s.resultDesc}>{item.description}</p>
                          )}
                          {item.price != null && (
                            <span className={s.resultPrice}>
                              {Number(item.price).toLocaleString()}원
                            </span>
                          )}
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>
            )}

            {meta && meta.total_pages > 1 && (
              <div className={s.pagination}>
                <span className={s.pageInfo}>
                  {meta.page} / {meta.total_pages} 페이지 (총 {meta.total}건)
                </span>
              </div>
            )}
          </>
        )}

        {!query && (
          <EmptyState
            icon={Search}
            title="검색어를 입력하세요"
            description="상품, 핫딜, 커뮤니티 글, 동네 마트 정보를 통합 검색할 수 있습니다."
          />
        )}
      </div>
    </div>
  );
}
