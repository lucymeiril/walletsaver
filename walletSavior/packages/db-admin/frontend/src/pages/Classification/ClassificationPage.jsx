import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import {
  ChevronRight, ChevronDown, Plus, Pencil, Trash2, X,
  Package, Search, FolderInput, AlertTriangle, Tag, Key,
  Sparkles, FolderTree,
} from 'lucide-react';
import useDbAdminStore from '../../stores/dbAdminStore';
import s from './ClassificationPage.module.css';

/* ── 트리 유틸 ── */
function flattenTree(nodes, depth = 0) {
  const result = [];
  for (const n of nodes) {
    result.push({ id: n.id, name: n.name, depth });
    if (n.children?.length) result.push(...flattenTree(n.children, depth + 1));
  }
  return result;
}

function countProducts(node) {
  const own = node.productCount ?? 0;
  return own + (node.children || []).reduce((sum, c) => sum + countProducts(c), 0);
}

function collectDescendantIds(node) {
  const ids = new Set([node.id]);
  for (const c of node.children || []) {
    for (const id of collectDescendantIds(c)) ids.add(id);
  }
  return ids;
}

function findNode(nodes, id) {
  for (const n of nodes) {
    if (n.id === id) return n;
    if (n.children?.length) {
      const found = findNode(n.children, id);
      if (found) return found;
    }
  }
  return null;
}

function filterTree(nodes, query) {
  if (!query) return nodes;
  const q = query.toLowerCase();
  return nodes.reduce((acc, node) => {
    const nameMatch = node.name.toLowerCase().includes(q) || node.id.toLowerCase().includes(q);
    const filtered = filterTree(node.children || [], query);
    if (nameMatch || filtered.length > 0) acc.push({ ...node, children: filtered });
    return acc;
  }, []);
}

function countKeywordsForCategory(keywords, categoryId) {
  return keywords.filter(k => (k.categoryId || k.category_id) === categoryId).length;
}

/* ── 한국어 동의어 매핑 (확장 가능) ── */
const SYNONYM_MAP = {
  '닭고기': ['닭', '치킨', '닭가슴살', '닭다리', '닭날개', '닭안심'],
  '돼지고기': ['돼지', '삼겹살', '목살', '앞다리', '뒷다리', '갈비', '등심'],
  '소고기': ['소', '한우', '육우', '수입소', '등심', '안심', '갈비', '차돌박이'],
  '삼겹살': ['삼겹', '오겹살', '대패삼겹살', '구이용'],
  '우유': ['흰우유', '저지방우유', '멸균우유'],
  '계란': ['달걀', '유정란', '무정란'],
  '쌀': ['백미', '현미', '찹쌀', '잡곡'],
  '라면': ['컵라면', '봉지라면', '인스턴트'],
  '커피': ['원두', '커피믹스', '캡슐커피', '아메리카노'],
  '과일': ['사과', '배', '귤', '감귤', '포도', '딸기', '바나나', '수박', '참외'],
  '채소': ['배추', '무', '양파', '대파', '마늘', '고추', '감자', '당근', '시금치'],
  '생수': ['물', '탄산수', '미네랄워터'],
  '두부': ['순두부', '연두부', '부침두부'],
  '김치': ['배추김치', '총각김치', '깍두기', '열무김치'],
  '빵': ['식빵', '모닝빵', '바게트', '크로아상'],
  '생선': ['고등어', '갈치', '연어', '참치', '광어', '우럭'],
  '새우': ['대하', '꽃새우', '냉동새우', '건새우'],
  '오징어': ['한치', '꼴뚜기', '냉동오징어'],
  '버터': ['무염버터', '가염버터', '식물성버터'],
  '치즈': ['슬라이스치즈', '모짜렐라', '크림치즈', '체다치즈'],
  '요거트': ['요구르트', '그릭요거트', '떠먹는요거트'],
};

const KNOWN_SUFFIXES = ['고기', '가격', '할인', '세일', '특가'];

/* ── 카테고리 이름으로 키워드 자동 생성 ── */
function generateKeywordsFromCategory(node, categories) {
  const suggestions = new Set();
  const name = node.name.trim();
  if (!name) return [];

  // 1. 원래 이름
  suggestions.add(name);

  // 2. 동의어 매핑
  if (SYNONYM_MAP[name]) {
    SYNONYM_MAP[name].forEach(s => suggestions.add(s));
  }

  // 3. 복합어 분리 (알려진 접미사 기반)
  for (const suffix of KNOWN_SUFFIXES) {
    if (name.endsWith(suffix) && name.length > suffix.length) {
      const prefix = name.slice(0, -suffix.length);
      if (prefix.length >= 1) suggestions.add(prefix);
    }
  }

  // 4. 부모 이름 + 현재 이름 조합
  if (node.parent_id) {
    const parent = findNode(categories, node.parent_id);
    if (parent) {
      suggestions.add(`${parent.name}${name}`);
      suggestions.add(`${parent.name} ${name}`);
    }
  }

  // 5. 가격 키워드
  suggestions.add(`${name} 가격`);

  return [...suggestions];
}

/* ── 메인 컴포넌트 ── */
export default function ClassificationPage() {
  const {
    categories, addCategory, updateCategory, deleteCategory, moveCategory, fetchCategories,
    keywords, addKeyword, updateKeyword, deleteKeyword,
    fetchKeywords, fetchKeywordStats, keywordStats,
    loading,
  } = useDbAdminStore();

  // 카테고리 트리 상태
  const [expanded, setExpanded] = useState(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCatId, setSelectedCatId] = useState(null);

  // 카테고리 모달
  const [catModal, setCatModal] = useState(null);
  const [catForm, setCatForm] = useState({});

  // 키워드 관련
  const [kwSearch, setKwSearch] = useState('');
  const [kwModal, setKwModal] = useState(null);
  const [kwForm, setKwForm] = useState({});
  const [synonymInput, setSynonymInput] = useState('');
  const [generatedKws, setGeneratedKws] = useState([]);
  const [generating, setGenerating] = useState(false);

  // 토스트
  const [toast, setToast] = useState(null);
  const debounceRef = useRef(null);

  // 데이터 로드
  useEffect(() => {
    fetchCategories();
    fetchKeywordStats();
  }, [fetchCategories, fetchKeywordStats]);

  // 카테고리 선택 시 키워드 로드
  useEffect(() => {
    if (selectedCatId) {
      fetchKeywords({ category_id: selectedCatId, per_page: 100, sort_by: 'search_count', sort_dir: 'desc' });
    }
  }, [selectedCatId, fetchKeywords]);

  // 트리 필터
  const filteredCategories = useMemo(
    () => filterTree(categories, searchQuery),
    [categories, searchQuery],
  );

  const effectiveExpanded = useMemo(() => {
    if (!searchQuery) return expanded;
    const all = new Set();
    const collect = (nodes) => {
      for (const n of nodes) {
        if (n.children?.length) { all.add(n.id); collect(n.children); }
      }
    };
    collect(filteredCategories);
    return all;
  }, [searchQuery, expanded, filteredCategories]);

  const flatList = useMemo(() => flattenTree(categories), [categories]);

  const selectedNode = useMemo(
    () => selectedCatId ? findNode(categories, selectedCatId) : null,
    [categories, selectedCatId],
  );

  // 선택된 카테고리의 키워드 필터링
  const categoryKeywords = useMemo(() => {
    if (!selectedCatId) return [];
    let filtered = keywords.filter(k => (k.categoryId || k.category_id) === selectedCatId);
    if (kwSearch) {
      const q = kwSearch.toLowerCase();
      filtered = filtered.filter(k =>
        (k.keyword || k.word || '').toLowerCase().includes(q) ||
        (k.synonyms || []).some(syn => syn.toLowerCase().includes(q)),
      );
    }
    return filtered;
  }, [keywords, selectedCatId, kwSearch]);

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const expandAll = () => {
    const all = new Set();
    const collect = (nodes) => {
      for (const n of nodes) {
        if (n.children?.length) { all.add(n.id); collect(n.children); }
      }
    };
    collect(categories);
    setExpanded(all);
  };

  const collapseAll = () => setExpanded(new Set());

  const showToast = useCallback((msg, type = 'info') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  /* ── 카테고리 CRUD ── */
  const openAddCat = (parentId = null) => {
    setCatForm({ name: '', parentId, attributes: { origin: '', storage: '', grade: '' }, autoKeywords: true });
    setCatModal({ mode: 'add' });
  };

  const openEditCat = (cat) => {
    setCatForm({ name: cat.name, attributes: cat.attributes || { origin: '', storage: '', grade: '' } });
    setCatModal({ mode: 'edit', category: cat });
  };

  const openMoveCat = (cat) => {
    setCatForm({ newParentId: cat.parent_id || '' });
    setCatModal({ mode: 'move', category: cat });
  };

  const handleSaveCat = async () => {
    if (catModal.mode === 'add') {
      const parentId = catForm.parentId || null;
      const parentNode = parentId ? findNode(categories, parentId) : null;
      const slug = catForm.name.replace(/\s+/g, '-').toLowerCase();
      const autoId = parentNode ? `${parentNode.id}.${slug}` : slug;
      await addCategory(parentId, { id: autoId, name: catForm.name, attributes: catForm.attributes });

      // 자동 키워드 생성
      if (catForm.autoKeywords) {
        await fetchCategories();
        const newNode = { name: catForm.name, parent_id: parentId, id: autoId };
        const kwSuggestions = generateKeywordsFromCategory(newNode, categories);
        for (const word of kwSuggestions) {
          await addKeyword({ keyword: word, categoryId: autoId, synonyms: [] });
        }
        if (selectedCatId === autoId) {
          fetchKeywords({ category_id: autoId, per_page: 100, sort_by: 'search_count', sort_dir: 'desc' });
        }
        showToast(`카테고리와 키워드 ${kwSuggestions.length}개가 생성되었습니다.`, 'success');
      } else {
        showToast('카테고리가 추가되었습니다.', 'success');
      }
    } else if (catModal.mode === 'edit') {
      await updateCategory(catModal.category.id, { name: catForm.name, attributes: catForm.attributes });
      showToast('카테고리가 수정되었습니다.', 'success');
    } else if (catModal.mode === 'move') {
      await moveCategory(catModal.category.id, catForm.newParentId || null);
      showToast('카테고리가 이동되었습니다.', 'success');
    }
    setCatModal(null);
  };

  const handleDeleteCat = (cat) => {
    const count = countProducts(cat);
    const msg = count > 0
      ? `이 카테고리에 ${count}개의 상품이 소속되어 있습니다.\n삭제하면 상품의 카테고리가 해제됩니다. 계속하시겠습니까?`
      : '하위 카테고리도 함께 삭제됩니다. 계속하시겠습니까?';
    if (confirm(msg)) {
      deleteCategory(cat.id);
      if (selectedCatId === cat.id) setSelectedCatId(null);
      showToast('카테고리가 삭제되었습니다.', 'success');
    }
  };

  /* ── 키워드 CRUD ── */
  const openAddKw = () => {
    setKwForm({ keyword: '', searchCount: 0, synonyms: [], categoryId: selectedCatId || '' });
    setSynonymInput('');
    setKwModal({ mode: 'add' });
  };

  const openEditKw = (kw) => {
    setKwForm({ ...kw });
    setSynonymInput('');
    setKwModal({ mode: 'edit', keyword: kw });
  };

  const addSynonym = () => {
    const values = synonymInput.split(',').map(v => v.trim()).filter(Boolean);
    const syns = kwForm.synonyms || [];
    const newSyns = [...syns];
    values.forEach(val => { if (!newSyns.includes(val)) newSyns.push(val); });
    setKwForm({ ...kwForm, synonyms: newSyns });
    setSynonymInput('');
  };

  const removeSynonym = (syn) => {
    setKwForm({ ...kwForm, synonyms: (kwForm.synonyms || []).filter(v => v !== syn) });
  };

  const handleSaveKw = async () => {
    const data = { ...kwForm, searchCount: Number(kwForm.searchCount) };
    if (kwModal.mode === 'add') {
      const result = await addKeyword(data);
      if (result?.status === 409) {
        showToast(result.message, 'error');
        return;
      }
      showToast('키워드가 추가되었습니다.', 'success');
    } else {
      await updateKeyword(kwModal.keyword.id, data);
      showToast('키워드가 수정되었습니다.', 'success');
    }
    setKwModal(null);
    if (selectedCatId) {
      fetchKeywords({ category_id: selectedCatId, per_page: 100, sort_by: 'search_count', sort_dir: 'desc' });
    }
  };

  const handleDeleteKw = async (id) => {
    if (confirm('키워드를 삭제하시겠습니까?')) {
      await deleteKeyword(id);
      showToast('키워드가 삭제되었습니다.', 'success');
      if (selectedCatId) {
        fetchKeywords({ category_id: selectedCatId, per_page: 100, sort_by: 'search_count', sort_dir: 'desc' });
      }
    }
  };

  const handleUnlinkKw = async (kw) => {
    await updateKeyword(kw.id, { ...kw, categoryId: '' });
    showToast('키워드 연결이 해제되었습니다.', 'success');
    if (selectedCatId) {
      fetchKeywords({ category_id: selectedCatId, per_page: 100, sort_by: 'search_count', sort_dir: 'desc' });
    }
  };

  /* ── 일괄 키워드 생성 ── */
  const handleBulkGenerate = async () => {
    if (!selectedNode) return;
    setGenerating(true);
    const suggestions = generateKeywordsFromCategory(selectedNode, categories);
    const existing = categoryKeywords.map(k => (k.keyword || k.word || '').toLowerCase());
    const newOnes = suggestions.filter(w => !existing.includes(w.toLowerCase()));
    setGeneratedKws(newOnes);
    setGenerating(false);
  };

  const confirmBulkGenerate = async () => {
    for (const word of generatedKws) {
      await addKeyword({ keyword: word, categoryId: selectedCatId, synonyms: [] });
    }
    showToast(`${generatedKws.length}개 키워드가 생성되었습니다.`, 'success');
    setGeneratedKws([]);
    fetchKeywords({ category_id: selectedCatId, per_page: 100, sort_by: 'search_count', sort_dir: 'desc' });
  };

  /* ── 빈 카테고리 수 ── */
  const emptyCount = useMemo(() => {
    let count = 0;
    const walk = (nodes) => {
      for (const n of nodes) {
        if (countProducts(n) === 0) count++;
        if (n.children?.length) walk(n.children);
      }
    };
    walk(categories);
    return count;
  }, [categories]);

  // 부모 경로 구하기
  const getCategoryPath = useCallback((node) => {
    if (!node) return '';
    const parts = node.id.split('.');
    return parts.join(' > ');
  }, []);

  return (
    <div className={s.page}>
      {/* 토스트 */}
      {toast && <div className={`${s.toast} ${s[toast.type]}`}>{toast.msg}</div>}

      <div className={s.header}>
        <h2 className={s.title}>
          <FolderTree size={22} />
          분류 관리
        </h2>
        <div className={s.headerActions}>
          <button className={s.addBtn} onClick={() => openAddCat(null)}>
            <Plus size={16} /> 최상위 카테고리 추가
          </button>
        </div>
      </div>

      {/* 빈 카테고리 안내 */}
      {emptyCount > 0 && (
        <div className={s.emptyBanner}>
          <AlertTriangle size={16} />
          <span>상품이 없는 빈 카테고리가 <strong>{emptyCount}개</strong> 있습니다.</span>
        </div>
      )}

      {/* ── 3패널 레이아웃 ── */}
      <div className={s.panels}>
        {/* ── 왼쪽: 카테고리 트리 ── */}
        <div className={s.leftPanel}>
          <div className={s.panelHeader}>
            <h3 className={s.panelTitle}>카테고리</h3>
            <div className={s.toggleBtns}>
              <button onClick={expandAll} className={s.toolBtn} title="전체 펼치기">전체 펼치기</button>
              <button onClick={collapseAll} className={s.toolBtn} title="전체 접기">전체 접기</button>
            </div>
          </div>

          <div className={s.searchWrap}>
            <Search size={14} className={s.searchIcon} />
            <input
              className={s.searchInput}
              placeholder="카테고리 검색..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button className={s.clearBtn} onClick={() => setSearchQuery('')}>
                <X size={14} />
              </button>
            )}
          </div>

          <div className={s.treeWrap}>
            {filteredCategories.length === 0 ? (
              <div className={s.emptyTree}>
                {searchQuery ? '검색 결과가 없습니다.' : '카테고리가 없습니다.'}
              </div>
            ) : (
              filteredCategories.map(cat => (
                <TreeNode
                  key={cat.id}
                  node={cat}
                  depth={0}
                  expanded={effectiveExpanded}
                  toggle={toggle}
                  selectedId={selectedCatId}
                  onSelect={setSelectedCatId}
                  onAdd={openAddCat}
                  onEdit={openEditCat}
                  onDelete={handleDeleteCat}
                  onMove={openMoveCat}
                />
              ))
            )}
          </div>
        </div>

        {/* ── 가운데: 카테고리 상세 ── */}
        <div className={s.centerPanel}>
          {selectedNode ? (
            <>
              <div className={s.panelHeader}>
                <h3 className={s.panelTitle}>카테고리 상세</h3>
              </div>
              <div className={s.detailContent}>
                <div className={s.detailName}>{selectedNode.name}</div>
                <div className={s.detailMeta}>
                  <div className={s.metaRow}>
                    <span className={s.metaLabel}>ID</span>
                    <code className={s.metaValue}>{selectedNode.id}</code>
                  </div>
                  <div className={s.metaRow}>
                    <span className={s.metaLabel}>경로</span>
                    <span className={s.metaValue}>{getCategoryPath(selectedNode)}</span>
                  </div>
                  <div className={s.metaRow}>
                    <span className={s.metaLabel}>상품 수</span>
                    <span className={s.metaValue}>
                      <Package size={14} /> {countProducts(selectedNode)}개
                      {selectedNode.productCount != null && selectedNode.productCount !== countProducts(selectedNode) && (
                        <span className={s.metaSub}> (직접 {selectedNode.productCount}개)</span>
                      )}
                    </span>
                  </div>
                  <div className={s.metaRow}>
                    <span className={s.metaLabel}>하위 카테고리</span>
                    <span className={s.metaValue}>{(selectedNode.children || []).length}개</span>
                  </div>
                  <div className={s.metaRow}>
                    <span className={s.metaLabel}>연결 키워드</span>
                    <span className={s.metaValue}>
                      <Key size={14} /> {categoryKeywords.length}개
                    </span>
                  </div>
                  {selectedNode.attributes && (
                    <>
                      {selectedNode.attributes.origin && (
                        <div className={s.metaRow}>
                          <span className={s.metaLabel}>원산지</span>
                          <span className={s.attrTag}>{selectedNode.attributes.origin}</span>
                        </div>
                      )}
                      {selectedNode.attributes.storage && (
                        <div className={s.metaRow}>
                          <span className={s.metaLabel}>보관</span>
                          <span className={s.attrTag}>{selectedNode.attributes.storage}</span>
                        </div>
                      )}
                      {selectedNode.attributes.grade && (
                        <div className={s.metaRow}>
                          <span className={s.metaLabel}>등급</span>
                          <span className={s.attrTag}>{selectedNode.attributes.grade}</span>
                        </div>
                      )}
                    </>
                  )}
                </div>

                <div className={s.detailActions}>
                  <button className={s.editBtn} onClick={() => openEditCat(selectedNode)}>
                    <Pencil size={14} /> 편집
                  </button>
                  <button className={s.moveBtn} onClick={() => openMoveCat(selectedNode)}>
                    <FolderInput size={14} /> 이동
                  </button>
                  <button className={s.subAddBtn} onClick={() => openAddCat(selectedNode.id)}>
                    <Plus size={14} /> 하위 추가
                  </button>
                  <button className={s.deleteBtn} onClick={() => handleDeleteCat(selectedNode)}>
                    <Trash2 size={14} /> 삭제
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className={s.emptyPanel}>
              <FolderTree size={40} className={s.emptyIcon} />
              <p>카테고리를 선택하세요</p>
              <span className={s.emptyHint}>왼쪽 트리에서 카테고리를 클릭하면 상세 정보가 표시됩니다</span>
            </div>
          )}
        </div>

        {/* ── 오른쪽: 연결된 키워드 ── */}
        <div className={s.rightPanel}>
          {selectedNode ? (
            <>
              <div className={s.panelHeader}>
                <h3 className={s.panelTitle}>
                  <Key size={16} /> 연결된 키워드
                </h3>
                <button className={s.kwAddBtn} onClick={openAddKw} title="키워드 추가">
                  <Plus size={14} />
                </button>
              </div>

              <div className={s.kwSearch}>
                <Search size={14} className={s.kwSearchIcon} />
                <input
                  className={s.kwSearchInput}
                  placeholder="키워드 검색..."
                  value={kwSearch}
                  onChange={e => setKwSearch(e.target.value)}
                />
              </div>

              <div className={s.kwList}>
                {categoryKeywords.length === 0 ? (
                  <div className={s.emptyKw}>
                    {kwSearch ? '검색 결과가 없습니다.' : '연결된 키워드가 없습니다.'}
                  </div>
                ) : (
                  categoryKeywords.map(kw => (
                    <div key={kw.id} className={s.kwItem}>
                      <div className={s.kwInfo}>
                        <span className={s.kwName}>
                          <Tag size={12} /> {kw.keyword || kw.word}
                        </span>
                        <span className={s.kwCount}>검색 {(kw.searchCount ?? 0).toLocaleString()}회</span>
                        {(kw.synonyms || []).length > 0 && (
                          <div className={s.kwSynonyms}>
                            {kw.synonyms.map(syn => (
                              <span key={syn} className={s.synTag}>{syn}</span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className={s.kwActions}>
                        <button title="수정" onClick={() => openEditKw(kw)}><Pencil size={13} /></button>
                        <button title="연결 해제" onClick={() => handleUnlinkKw(kw)}><X size={13} /></button>
                        <button title="삭제" onClick={() => handleDeleteKw(kw.id)}><Trash2 size={13} /></button>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* 일괄 키워드 생성 */}
              <div className={s.bulkSection}>
                <button
                  className={s.bulkBtn}
                  onClick={handleBulkGenerate}
                  disabled={generating}
                >
                  <Sparkles size={14} /> 일괄 키워드 생성
                </button>
                {generatedKws.length > 0 && (
                  <div className={s.bulkPreview}>
                    <span className={s.bulkLabel}>생성될 키워드:</span>
                    <div className={s.bulkTags}>
                      {generatedKws.map(w => (
                        <span key={w} className={s.bulkTag}>
                          {w}
                          <button onClick={() => setGeneratedKws(prev => prev.filter(v => v !== w))}>
                            <X size={10} />
                          </button>
                        </span>
                      ))}
                    </div>
                    <div className={s.bulkActions}>
                      <button className={s.bulkConfirm} onClick={confirmBulkGenerate}>
                        {generatedKws.length}개 생성
                      </button>
                      <button className={s.bulkCancel} onClick={() => setGeneratedKws([])}>취소</button>
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className={s.emptyPanel}>
              <Key size={40} className={s.emptyIcon} />
              <p>키워드</p>
              <span className={s.emptyHint}>카테고리 선택 시 연결된 키워드가 자동 표시됩니다</span>
            </div>
          )}
        </div>
      </div>

      {/* 하단 안내 */}
      <div className={s.footer}>
        💡 카테고리를 추가하면 키워드가 자동 생성됩니다. 카테고리 선택 후 키워드를 직접 추가하거나 일괄 생성할 수 있습니다.
      </div>

      {/* ── 카테고리 모달 ── */}
      {catModal && (
        <div className={s.overlay} onClick={() => setCatModal(null)}>
          <div className={s.modal} onClick={e => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <h3>
                {catModal.mode === 'add' && '카테고리 추가'}
                {catModal.mode === 'edit' && '카테고리 수정'}
                {catModal.mode === 'move' && '카테고리 이동'}
              </h3>
              <button onClick={() => setCatModal(null)}><X size={18} /></button>
            </div>
            <div className={s.form}>
              {(catModal.mode === 'add' || catModal.mode === 'edit') && (
                <>
                  {catModal.mode === 'add' && (
                    <label>
                      부모 카테고리
                      <select
                        value={catForm.parentId || ''}
                        onChange={e => setCatForm({ ...catForm, parentId: e.target.value || null })}
                      >
                        <option value="">없음 (최상위)</option>
                        {flatList.map(c => (
                          <option key={c.id} value={c.id}>{'─'.repeat(c.depth)} {c.name}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label>
                    이름
                    <input
                      value={catForm.name}
                      onChange={e => setCatForm({ ...catForm, name: e.target.value })}
                      placeholder="예: 소고기"
                    />
                  </label>
                  {catModal.mode === 'add' && catForm.name && (
                    <div className={s.idPreview}>
                      ID 미리보기:{' '}
                      <code>
                        {catForm.parentId
                          ? `${findNode(categories, catForm.parentId)?.id || catForm.parentId}.${catForm.name.replace(/\s+/g, '-').toLowerCase()}`
                          : catForm.name.replace(/\s+/g, '-').toLowerCase()}
                      </code>
                    </div>
                  )}
                  <label>
                    등급
                    <input
                      value={catForm.attributes?.grade || ''}
                      onChange={e => setCatForm({ ...catForm, attributes: { ...catForm.attributes, grade: e.target.value } })}
                      placeholder="예: 1등급, 1++등급"
                    />
                  </label>
                  <label>
                    원산지
                    <input
                      value={catForm.attributes?.origin || ''}
                      onChange={e => setCatForm({ ...catForm, attributes: { ...catForm.attributes, origin: e.target.value } })}
                      placeholder="예: 국내산, 수입산"
                    />
                  </label>
                  <label>
                    보관 방법
                    <select
                      value={catForm.attributes?.storage || ''}
                      onChange={e => setCatForm({ ...catForm, attributes: { ...catForm.attributes, storage: e.target.value } })}
                    >
                      <option value="">선택</option>
                      <option value="냉장">냉장</option>
                      <option value="냉동">냉동</option>
                      <option value="상온">상온</option>
                    </select>
                  </label>
                  {catModal.mode === 'add' && (
                    <label className={s.checkLabel}>
                      <input
                        type="checkbox"
                        checked={catForm.autoKeywords ?? true}
                        onChange={e => setCatForm({ ...catForm, autoKeywords: e.target.checked })}
                      />
                      카테고리 이름으로 키워드 자동 생성
                    </label>
                  )}
                </>
              )}
              {catModal.mode === 'move' && (
                <>
                  <p className={s.moveInfo}>
                    <strong>{catModal.category.name}</strong>의 새 부모 카테고리를 선택하세요.
                  </p>
                  <label>
                    새 부모 카테고리
                    <select
                      value={catForm.newParentId || ''}
                      onChange={e => setCatForm({ ...catForm, newParentId: e.target.value || null })}
                    >
                      <option value="">없음 (최상위로 이동)</option>
                      {flatList
                        .filter(c => {
                          const node = findNode(categories, catModal.category.id);
                          if (!node) return c.id !== catModal.category.id;
                          const descendants = collectDescendantIds(node);
                          return !descendants.has(c.id);
                        })
                        .map(c => (
                          <option key={c.id} value={c.id}>{'─'.repeat(c.depth)} {c.name}</option>
                        ))}
                    </select>
                  </label>
                </>
              )}
              <div className={s.formActions}>
                <button className={s.cancelBtn} onClick={() => setCatModal(null)}>취소</button>
                <button
                  className={s.saveBtn}
                  onClick={handleSaveCat}
                  disabled={catModal.mode !== 'move' && !catForm.name?.trim()}
                >
                  {catModal.mode === 'move' ? '이동' : '저장'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── 키워드 모달 ── */}
      {kwModal && (
        <div className={s.overlay} onClick={() => setKwModal(null)}>
          <div className={s.modal} onClick={e => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <h3>{kwModal.mode === 'add' ? '키워드 추가' : '키워드 수정'}</h3>
              <button onClick={() => setKwModal(null)}><X size={18} /></button>
            </div>
            <div className={s.form}>
              <label>
                키워드
                <input value={kwForm.keyword || ''} onChange={e => setKwForm({ ...kwForm, keyword: e.target.value })} />
              </label>
              <label>
                검색 횟수
                <input type="number" value={kwForm.searchCount || 0} onChange={e => setKwForm({ ...kwForm, searchCount: e.target.value })} />
              </label>
              <label>
                연결 카테고리
                <select value={kwForm.categoryId || ''} onChange={e => setKwForm({ ...kwForm, categoryId: e.target.value })}>
                  <option value="">선택 안 함</option>
                  {flatList.map(c => (
                    <option key={c.id} value={c.id}>{'─'.repeat(c.depth)} {c.name}</option>
                  ))}
                </select>
              </label>
              <label>동의어</label>
              <div className={s.synonymEditor}>
                <div className={s.synonymTags}>
                  {(kwForm.synonyms || []).map(syn => (
                    <span key={syn} className={s.editTag}>
                      {syn}
                      <button onClick={() => removeSynonym(syn)}><X size={12} /></button>
                    </span>
                  ))}
                </div>
                <div className={s.synonymAdd}>
                  <input
                    value={synonymInput}
                    onChange={e => setSynonymInput(e.target.value)}
                    placeholder="동의어 입력 (콤마로 구분)"
                    onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addSynonym())}
                  />
                  <button type="button" onClick={addSynonym}><Tag size={14} /> 추가</button>
                </div>
              </div>
              <div className={s.formActions}>
                <button className={s.cancelBtn} onClick={() => setKwModal(null)}>취소</button>
                <button className={s.saveBtn} onClick={handleSaveKw}>저장</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 트리 노드 컴포넌트 ── */
function TreeNode({ node, depth, expanded, toggle, selectedId, onSelect, onAdd, onEdit, onDelete, onMove }) {
  const hasChildren = node.children && node.children.length > 0;
  const isOpen = expanded.has(node.id);
  const isSelected = node.id === selectedId;
  const totalCount = countProducts(node);
  const ownCount = node.productCount ?? 0;
  const isEmpty = totalCount === 0;

  return (
    <div className={s.treeNode}>
      <div
        className={`${s.nodeRow} ${isEmpty ? s.emptyNode : ''} ${isSelected ? s.selectedNode : ''}`}
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
        onClick={() => onSelect(node.id)}
      >
        <button
          className={s.expandBtn}
          onClick={e => { e.stopPropagation(); hasChildren && toggle(node.id); }}
          style={{ visibility: hasChildren ? 'visible' : 'hidden' }}
        >
          {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <span className={`${s.nodeName} ${isEmpty ? s.emptyName : ''}`}>{node.name}</span>
        <span className={`${s.badge} ${ownCount === 0 ? s.badgeEmpty : ''}`}>
          {ownCount}
        </span>
        <div className={s.nodeActions}>
          <button title="하위 추가" onClick={e => { e.stopPropagation(); onAdd(node.id); }}><Plus size={12} /></button>
          <button title="수정" onClick={e => { e.stopPropagation(); onEdit(node); }}><Pencil size={12} /></button>
          <button title="삭제" onClick={e => { e.stopPropagation(); onDelete(node); }}><Trash2 size={12} /></button>
        </div>
      </div>
      {isOpen && hasChildren && (
        <div className={s.children}>
          {node.children.map(child => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
              selectedId={selectedId}
              onSelect={onSelect}
              onAdd={onAdd}
              onEdit={onEdit}
              onDelete={onDelete}
              onMove={onMove}
            />
          ))}
        </div>
      )}
    </div>
  );
}
