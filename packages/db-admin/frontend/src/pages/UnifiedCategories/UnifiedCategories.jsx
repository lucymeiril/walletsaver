import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import s from './UnifiedCategories.module.css';

const MARTS = ['emart', 'homeplus', 'lottemart', 'costco'];
const MART_LABEL = { emart: '이마트', homeplus: '홈플러스', lottemart: '롯데마트', costco: '코스트코' };

function flattenTree(nodes, depth = 0, acc = []) {
  for (const node of nodes || []) {
    acc.push({ ...node, depth });
    flattenTree(node.children || [], depth + 1, acc);
  }
  return acc;
}

export default function UnifiedCategories() {
  const [tree, setTree] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [mart, setMart] = useState('lottemart');
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const flat = useMemo(() => flattenTree(tree), [tree]);
  const visibleMappings = useMemo(() => {
    if (!selectedCategory) return mappings;
    return mappings.filter((row) => row.unified_category_id === selectedCategory.id || row.review_status === 'needs_review');
  }, [mappings, selectedCategory]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([api.getUnifiedCategoryTree(), api.getCategoryMappings(mart)])
      .then(([treeData, mappingData]) => {
        if (!alive) return;
        setTree(treeData);
        setMappings(mappingData);
        setError('');
      })
      .catch((err) => alive && setError(err.message || '카테고리 매핑을 불러오지 못했습니다.'))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [mart]);

  const saveMapping = async (row) => {
    const unifiedCategoryId = drafts[row.mart_native_id] || row.unified_category_id || selectedCategory?.id;
    if (!unifiedCategoryId) {
      setError('매핑할 통합 카테고리를 선택하세요.');
      return;
    }
    try {
      await api.saveCategoryMapping({
        mart: row.mart,
        mart_native_id: row.mart_native_id,
        mart_native_path: row.mart_native_path,
        unified_category_id: unifiedCategoryId,
        confidence: 1,
      });
      setMappings(await api.getCategoryMappings(mart));
      setError('');
    } catch (err) {
      setError(err.message || '매핑 저장 실패');
    }
  };

  return (
    <div className={s.page}>
      <div className={s.header}>
        <div>
          <h1 className={s.title}>카테고리 통합 트리</h1>
          <p className={s.subtitle}>Round R G2 통합 카테고리와 4사 native category 매핑을 관리합니다.</p>
        </div>
        {loading && <span className={s.badge}>로딩 중...</span>}
      </div>

      {error && <div className={s.error}>{error}</div>}

      <div className={s.grid}>
        <section className={s.panel}>
          <h2>통합 트리</h2>
          <div className={s.tree}>
            {flat.map((node) => (
              <button
                key={node.id}
                className={`${s.treeButton} ${selectedCategory?.id === node.id ? s.active : ''}`}
                style={{ paddingLeft: 8 + node.depth * 18 }}
                onClick={() => setSelectedCategory(node)}
              >
                {node.name_ko} <span className={s.badge}>{node.id}</span>
              </button>
            ))}
          </div>
        </section>

        <section className={s.panel}>
          <h2>마트별 매핑 {selectedCategory ? `— ${selectedCategory.name_ko}` : ''}</h2>
          <div className={s.tabs}>
            {MARTS.map((value) => (
              <button key={value} className={`${s.tab} ${mart === value ? s.active : ''}`} onClick={() => setMart(value)}>
                {MART_LABEL[value]}
              </button>
            ))}
          </div>

          <div className={s.mappingList}>
            {visibleMappings.map((row) => (
              <article key={`${row.mart}:${row.mart_native_id}`} className={`${s.mappingCard} ${row.review_status === 'needs_review' ? s.needsReview : ''}`}>
                <div className={s.mappingTop}>
                  <span>{row.mart_native_id}</span>
                  <span className={s.badge}>{row.review_status === 'needs_review' ? 'review 필요' : row.trust}</span>
                </div>
                <div className={s.path}>{row.mart_native_path || '(native path 없음)'}</div>
                <div className={s.path}>현재: {row.unified_category_name_ko || '미매핑'} · 상품 {row.product_count}개</div>
                <div className={s.controls}>
                  <select
                    className={s.select}
                    value={drafts[row.mart_native_id] || row.unified_category_id || selectedCategory?.id || ''}
                    onChange={(event) => setDrafts((prev) => ({ ...prev, [row.mart_native_id]: event.target.value }))}
                  >
                    <option value="">통합 카테고리 선택</option>
                    {flat.map((node) => (
                      <option key={node.id} value={node.id}>{'　'.repeat(node.depth)}{node.name_ko} ({node.id})</option>
                    ))}
                  </select>
                  <button className={s.save} onClick={() => saveMapping(row)}>human 저장</button>
                </div>
              </article>
            ))}
            {!visibleMappings.length && <p className={s.path}>표시할 매핑이 없습니다.</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
