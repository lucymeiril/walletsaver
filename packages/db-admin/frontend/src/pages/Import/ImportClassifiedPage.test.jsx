import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ImportClassifiedPage from './ImportClassifiedPage';

vi.mock('../../api/client', () => ({
  api: {
    previewImport: vi.fn(),
    confirmImport: vi.fn(),
    getImportFailureCsvUrl: vi.fn((id) => `/api/import/classified/failure-csv/${id}`),
  },
}));

import { api } from '../../api/client';

const PREVIEW_OK = {
  ok: true,
  batch_id: 'batch_abc',
  trace_id: 'tr_abc123',
  mode: 'strict',
  total_rows: 5,
  valid_rows: 5,
  diff: {
    added: 3,
    updated: 1,
    conflicts: 1,
    unchanged: 0,
    total_incoming: 5,
    preview_rows: [
      { match_key: 'mk_001', action: 'add', category_id: 'cat_food', confidence: 0.95, source: 'external-ai' },
      { match_key: 'mk_002', action: 'add', category_id: 'cat_drink', confidence: 0.88, source: 'external-ai' },
      { match_key: 'mk_003', action: 'update', category_id: 'cat_snack', confidence: 0.72, source: 'human' },
    ],
  },
  errors: [],
  warnings: [],
};

const CONFIRM_OK = {
  ok: true,
  trace_id: 'tr_abc123',
  mode: 'strict',
  total_rows: 5,
  valid_rows: 5,
  inserted: 3,
  updated: 1,
  conflicts: 1,
  skipped: 0,
  errors: [],
  warnings: [],
  failure_csv_url: null,
  idempotent: false,
};

const PREVIEW_WITH_ERRORS = {
  ok: false,
  mode: 'strict',
  total_rows: 3,
  valid_rows: 0,
  errors: [{ row: 1, message: 'category_id 없음' }],
  warnings: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.previewImport.mockResolvedValue(PREVIEW_OK);
  api.confirmImport.mockResolvedValue(CONFIRM_OK);
});

function makeFile(name = 'classified.jsonl') {
  return new File(
    ['{"match_key":"a","category_id":"b","confidence":0.9,"source":"external-ai"}'],
    name,
    { type: 'application/octet-stream' },
  );
}

function renderPage() {
  render(<ImportClassifiedPage />);
}

describe('ImportClassifiedPage', () => {
  it('shows the single current classification import flow', () => {
    renderPage();
    expect(screen.getByText('외부 분류 결과 Import')).toBeTruthy();
    expect(screen.getByLabelText('파일 업로드 영역')).toBeTruthy();
    expect(screen.queryByText(/Bundle \(3종 파일\)/)).toBeNull();
    expect(screen.queryByText(/Legacy/)).toBeNull();
    expect(screen.getByTestId('preview-btn').disabled).toBe(true);
  });

  it('accepts jsonl/csv and enables preview after file selection', () => {
    renderPage();
    const zone = screen.getByLabelText('파일 업로드 영역');
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile('sample.jsonl')] } });

    expect(screen.getByText('sample.jsonl')).toBeTruthy();
    expect(screen.getByTestId('preview-btn').disabled).toBe(false);
  });

  it('rejects unrelated file extensions', () => {
    renderPage();
    const zone = screen.getByLabelText('파일 업로드 영역');
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(['data'], 'data.yaml', { type: 'text/yaml' })] },
    });

    expect(screen.getByTestId('preview-btn').disabled).toBe(true);
  });

  it('previews matching changes without creating taxonomy/products', async () => {
    renderPage();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));

    await waitFor(() => expect(api.previewImport).toHaveBeenCalledTimes(1));
    expect(api.previewImport).toHaveBeenCalledWith(
      expect.any(File),
      'strict',
      expect.any(Object),
    );

    const counts = await screen.findByTestId('diff-counts');
    expect(counts.textContent).toContain('추가');
    expect(counts.textContent).toContain('수정');
    expect(screen.getByText('mk_001')).toBeTruthy();
  });

  it('reviews server-resolved unified targets and reports unchanged matching without claiming a new import', async () => {
    const targets = [{ match_key: 'existing-source-key', public_product_id: 'prod-existing',
      public_variant_id: 'var-existing', unified_category_id: 'food.drinks.water',
      category_path: [{ id: 'food', name: '식품' }, { id: 'food.drinks', name: '음료' }, { id: 'food.drinks.water', name: '생수' }],
      package_quantity: 2000, package_unit: 'ml', bundle_count: 6, display_unit: '2L×6' }];
    api.previewImport.mockResolvedValueOnce({ ...PREVIEW_OK, total_rows: 1, valid_rows: 1,
      normalized_targets: targets, diff: { added: 0, updated: 0, conflicts: 0, unchanged: 1,
        total_incoming: 1, preview_rows: [{ match_key: 'existing-source-key', action: 'unchanged', category_id: null }] } });
    api.confirmImport.mockResolvedValueOnce({ ...CONFIRM_OK, total_rows: 1, valid_rows: 1,
      inserted: 0, updated: 0, conflicts: 0, skipped: 1, normalized_targets: targets });
    renderPage();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), { dataTransfer: { files: [makeFile()] } });
    fireEvent.click(screen.getByTestId('preview-btn'));
    const review = await screen.findByRole('region', { name: '서버 검증 대상' });
    expect(review.textContent).toContain('식품 → 음료 → 생수');
    expect(review.textContent).toContain('food.drinks.water');
    expect(review.textContent).toContain('prod-existing');
    expect(review.textContent).toContain('var-existing');
    expect(review.textContent).toContain('판매 규격: 2L×6');
    expect(review.textContent).not.toContain('2000ml ×6');
    expect(review.querySelector('input, select')).toBeNull();
    fireEvent.click(screen.getByTestId('confirm-btn'));
    await screen.findByTestId('result-counts');
    expect(screen.getByRole('region', { name: '서버 검증 대상' }).textContent).toContain('var-existing');
    expect(screen.getByRole('alert').textContent).toContain('변경 없음 · 기존 매칭 유지');
    expect(screen.queryByText('분류 결과 적용 완료')).toBeNull();
  });

  it('preserves nonexact display contents and never presents a null scalar bookkeeping multiplier as sold quantity', async () => {
    api.previewImport.mockResolvedValueOnce({ ...PREVIEW_OK, normalized_targets: [
      { match_key: 'unknown-contents', public_product_id: 'prod-unknown', public_variant_id: 'var-unknown',
        unified_category_id: 'food.fruit.grape', category_path: [{ id: 'food.fruit.grape', name: '포도' }],
        package_quantity: null, package_unit: null, bundle_count: 1, display_unit: null },
      { match_key: 'approximate-contents', public_product_id: 'prod-approximate', public_variant_id: 'var-approximate',
        unified_category_id: 'food.fruit.grape', category_path: [{ id: 'food.fruit.grape', name: '포도' }],
        package_quantity: null, package_unit: null, bundle_count: 1, display_unit: '씨없는블랙포도3.6kg내외' },
      { match_key: 'known-scalar', public_product_id: 'prod-scalar', public_variant_id: 'var-scalar',
        unified_category_id: 'food.drinks.water', category_path: [],
        package_quantity: 2000, package_unit: 'ml', bundle_count: 6, display_unit: '' },
    ] });
    renderPage();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), { dataTransfer: { files: [makeFile()] } });
    fireEvent.click(screen.getByTestId('preview-btn'));
    const review = await screen.findByRole('region', { name: '서버 검증 대상' });
    expect(review.textContent).toContain('판매 규격: 미확인');
    expect(review.textContent).toContain('판매 규격: 씨없는블랙포도3.6kg내외');
    expect(review.textContent).toContain('판매 규격: 2000ml ×6');
    expect(review.textContent).not.toContain('미확인 ×1');
    expect(review.textContent).not.toContain('3.6kg내외 ×1');
  });

  it('shows conflicts from the matching diff', async () => {
    renderPage();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));

    expect(await screen.findByTestId('conflict-box')).toBeTruthy();
  });

  it('confirms with the preview trace id', async () => {
    renderPage();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));

    await screen.findByTestId('confirm-btn');
    fireEvent.click(screen.getByTestId('confirm-btn'));

    await waitFor(() => expect(api.confirmImport).toHaveBeenCalledTimes(1));
    expect(api.confirmImport).toHaveBeenCalledWith(
      expect.any(File),
      'strict',
      'tr_abc123',
      expect.any(Object),
    );
    expect((await screen.findByTestId('result-counts')).textContent).toContain('삽입');
  });

  it('shows failure csv when the current import API returns one', async () => {
    api.confirmImport.mockResolvedValueOnce({
      ...CONFIRM_OK,
      failure_csv_url: '/api/import/classified/failure-csv/tr_abc123',
    });

    renderPage();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));
    await screen.findByTestId('confirm-btn');
    fireEvent.click(screen.getByTestId('confirm-btn'));

    expect((await screen.findByTestId('csv-download')).href).toContain('failure-csv');
  });

  it('does not allow confirm when strict validation fails', async () => {
    api.previewImport.mockResolvedValueOnce(PREVIEW_WITH_ERRORS);

    renderPage();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));

    expect((await screen.findByTestId('confirm-btn')).disabled).toBe(true);
  });

  it('passes lenient mode to the current matching import API', async () => {
    renderPage();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByDisplayValue('lenient'));
    fireEvent.click(screen.getByTestId('preview-btn'));

    await waitFor(() => expect(api.previewImport).toHaveBeenCalledWith(
      expect.any(File),
      'lenient',
      expect.any(Object),
    ));
  });
});
