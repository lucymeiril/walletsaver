import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import ClassificationPage from './ClassificationPage';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: {
  getUnifiedCategoryTree: vi.fn(), getCategories: vi.fn(), getKeywordStats: vi.fn(),
  getKeywords: vi.fn(), updateKeyword: vi.fn(), createKeyword: vi.fn(),
} }));
const tree = [{ id: 'food', name_ko: '식품', parent_id: null, level: 1, children: [
  { id: 'food.coffee', name_ko: '커피', parent_id: 'food', level: 2, children: [] },
] }];
const row = { id: 7, word: '커피원두', synonyms: ['원두'], is_active: true,
  category_id: 'legacy-coffee', unified_category_id: 'food.coffee', search_count: 3 };
beforeEach(() => {
  vi.clearAllMocks();
  useDbAdminStore.setState({ categories: [], unifiedCategories: [], keywords: [], keywordQuery: {},
    error: null, unifiedCategoryError: null, loadingCategories: false, loadingUnifiedCategories: false, loadingKeywords: false });
  api.getUnifiedCategoryTree.mockResolvedValue(tree);
  api.getCategories.mockResolvedValue([{ id: 'legacy-coffee', name: '기존 커피', productCount: 2, children: [] }]);
  api.getKeywordStats.mockResolvedValue({ total: 1, unused_count: 0 });
  api.getKeywords.mockImplementation(async params => ({ items: params.unified_category_id === 'food.coffee' || params.category_id === 'legacy-coffee' ? [row] : [], total: 1 }));
  api.updateKeyword.mockResolvedValue({}); api.createKeyword.mockResolvedValue({});
});
afterEach(cleanup);
async function selectLeaf() {
  render(<ClassificationPage />);
  await screen.findByText('식품');
  fireEvent.click(screen.getByTitle('전체 펼치기'));
  fireEvent.click(screen.getByText('커피'));
  await screen.findByText('커피원두');
}
describe('classification namespaces', () => {
  it('defaults to read-only unified tree, leaf-filtered keywords and no legacy product zeros', async () => {
    render(<ClassificationPage />);
    fireEvent.click(await screen.findByText('식품'));
    expect(screen.getByTitle('키워드 추가').disabled).toBe(true);
    expect(api.getKeywords).not.toHaveBeenCalled();
    expect(screen.queryByText('최상위 카테고리 추가')).toBeNull();
    expect(screen.queryByTitle('하위 추가')).toBeNull();
    expect(screen.getByText('통합 상품 수 미조회')).toBeTruthy();
    expect(screen.queryByText(/상품이 없는 빈 카테고리/)).toBeNull();
    fireEvent.click(screen.getByTitle('전체 펼치기'));
    fireEvent.click(screen.getByText('커피'));
    await screen.findByText('커피원두');
    expect(api.getKeywords).toHaveBeenLastCalledWith(expect.objectContaining({ unified_category_id: 'food.coffee' }), expect.any(Object));
    expect(api.getKeywords.mock.calls.at(-1)[0]).not.toHaveProperty('category_id');
    expect(api.getCategories).not.toHaveBeenCalled();
  });
  it('updates unified word/synonyms/activation without clearing legacy reference, and creates only leaf keywords', async () => {
    await selectLeaf();
    fireEvent.click(screen.getByTitle('수정'));
    fireEvent.change(screen.getByLabelText('키워드'), { target: { value: '원두커피' } });
    fireEvent.change(screen.getByLabelText('활성 상태'), { target: { value: 'false' } });
    expect(screen.getByLabelText('연결 통합 말단 분류').querySelector('option[value="food"]')).toBeNull();
    fireEvent.click(screen.getByText('저장'));
    await waitFor(() => expect(api.updateKeyword).toHaveBeenCalledWith(7, {
      word: '원두커피', synonyms: ['원두'], unified_category_id: 'food.coffee', is_active: false,
    }));
    fireEvent.click(screen.getByTitle('키워드 추가'));
    fireEvent.change(screen.getByLabelText('키워드'), { target: { value: '새 원두' } });
    fireEvent.click(screen.getByText('저장'));
    await waitFor(() => expect(api.createKeyword).toHaveBeenCalledWith({ word: '새 원두', synonyms: [], unified_category_id: 'food.coffee' }));
    expect(useDbAdminStore.getState().keywords[0].category_id).toBe('legacy-coffee');
    expect(useDbAdminStore.getState().keywords[0].unified_category_id).toBe('food.coffee');
  });
  it('legacy edits omit unified binding and explicit unlink clears only the selected namespace', async () => {
    await selectLeaf();
    fireEvent.change(screen.getByLabelText('분류 체계'), { target: { value: 'legacy' } });
    fireEvent.click(await screen.findByText('기존 커피'));
    await screen.findByText('커피원두');
    expect(screen.getByText('최상위 카테고리 추가')).toBeTruthy();
    expect(api.getKeywords.mock.calls.at(-1)[0]).toEqual(expect.objectContaining({ category_id: 'legacy-coffee' }));
    fireEvent.click(screen.getAllByTitle('수정').at(-1));
    fireEvent.change(screen.getByLabelText('키워드'), { target: { value: '보존 원두' } });
    fireEvent.click(screen.getByText('저장'));
    await waitFor(() => expect(api.updateKeyword).toHaveBeenCalledWith(7, {
      word: '보존 원두', synonyms: ['원두'], category_id: 'legacy-coffee', is_active: true,
    }));
    fireEvent.click(screen.getByTitle('연결 해제'));
    await waitFor(() => expect(api.updateKeyword).toHaveBeenLastCalledWith(7, { category_id: null }));
  });
  it('preserves omitted unknown references and ignores superseded keyword responses', async () => {
    await useDbAdminStore.getState().updateKeyword(7, { keyword: '내용만', synonyms: [] });
    expect(api.updateKeyword).toHaveBeenCalledWith(7, { word: '내용만', synonyms: [] });
    let finish;
    api.getKeywords.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const old = useDbAdminStore.getState().fetchKeywords({ category_id: 'legacy-coffee' });
    await useDbAdminStore.getState().fetchKeywords({ unified_category_id: 'food.coffee' });
    finish({ items: [{ id: 99, word: '늦은 기존 결과', category_id: 'legacy-coffee' }] });
    await old;
    expect(useDbAdminStore.getState().keywords.map(k => k.id)).toEqual([7]);
  });
});
