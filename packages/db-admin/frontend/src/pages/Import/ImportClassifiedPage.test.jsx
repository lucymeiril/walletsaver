import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ImportClassifiedPage from './ImportClassifiedPage';

/* ── API mock ── */
vi.mock('../../api/client', () => ({
  api: {
    previewImport: vi.fn(),
    confirmImport: vi.fn(),
    getImportFailureCsvUrl: vi.fn((id) => `/api/import/classified/failure-csv/${id}`),
    previewBundleImport: vi.fn(),
    confirmBundleImport: vi.fn(),
    getBundleFailureCsvUrl: vi.fn((id) => `/api/import/bundle/${id}/failures.csv`),
  },
}));

import { api } from '../../api/client';

/* ── 샘플 데이터 ── */
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
      { match_key: 'mk_001', action: 'add',    category_id: 'cat_food', confidence: 0.95, source: 'ai' },
      { match_key: 'mk_002', action: 'add',    category_id: 'cat_drink', confidence: 0.88, source: 'ai' },
      { match_key: 'mk_003', action: 'update', category_id: 'cat_snack', confidence: 0.72, source: 'manual' },
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

/* ── helpers ── */
function makeFile(name = 'test.jsonl') {
  return new File(['{"match_key":"a","category_id":"b","confidence":0.9,"source":"ai"}'], name, {
    type: 'application/octet-stream',
  });
}

function renderLegacy() {
  render(<ImportClassifiedPage />);
  fireEvent.click(screen.getByTestId('tab-legacy'));
}

describe('ImportClassifiedPage', () => {
  it('초기 렌더: 드래그드롭 영역, 모드 라디오, Preview 버튼 표시', () => {
    renderLegacy();
    expect(screen.getByLabelText('파일 업로드 영역')).toBeTruthy();
    expect(screen.getByDisplayValue('strict')).toBeTruthy();
    expect(screen.getByDisplayValue('lenient')).toBeTruthy();
    expect(screen.getByTestId('preview-btn')).toBeTruthy();
    expect(screen.getByTestId('preview-btn').disabled).toBe(true); // 파일 없으면 비활성
  });

  it('파일 드롭 → 파일명 표시, Preview 버튼 활성화', () => {
    renderLegacy();
    const zone = screen.getByLabelText('파일 업로드 영역');
    const file = makeFile('sample.jsonl');

    fireEvent.drop(zone, {
      dataTransfer: { files: [file] },
    });

    expect(screen.getByText('sample.jsonl')).toBeTruthy();
    expect(screen.getByTestId('preview-btn').disabled).toBe(false);
  });

  it('잘못된 확장자 드롭 → 오류 toast, 파일 미설정', () => {
    renderLegacy();
    const zone = screen.getByLabelText('파일 업로드 영역');
    const badFile = new File(['data'], 'data.txt', { type: 'text/plain' });

    fireEvent.drop(zone, { dataTransfer: { files: [badFile] } });

    // preview 버튼 여전히 비활성
    expect(screen.getByTestId('preview-btn').disabled).toBe(true);
  });

  it('Preview 버튼 클릭 → api.previewImport 호출, diff 카운트 렌더', async () => {
    renderLegacy();
    const zone = screen.getByLabelText('파일 업로드 영역');
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile()] } });

    fireEvent.click(screen.getByTestId('preview-btn'));

    await waitFor(() => expect(api.previewImport).toHaveBeenCalledTimes(1));

    // 카운트 카드 렌더 확인
    const counts = await screen.findByTestId('diff-counts');
    expect(counts.textContent).toContain('3'); // added
    expect(counts.textContent).toContain('1'); // updated or conflicts
  });

  it('preview_rows 테이블 렌더 — 추가/수정 배지', async () => {
    renderLegacy();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));

    await screen.findByTestId('diff-counts');
    // 배지와 카운트 카드 레이블 두 곳에 "추가"가 있으므로 getAllByText 사용
    expect(screen.getAllByText('추가').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('수정').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('mk_001')).toBeTruthy();
  });

  it('conflict 항목 있으면 ImportConflictList 렌더 (빨간 톤 박스)', async () => {
    renderLegacy();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));

    const conflictBox = await screen.findByTestId('conflict-box');
    expect(conflictBox).toBeTruthy();
    // 빨간 border 스타일 확인 (class 기반)
    expect(conflictBox.className).toMatch(/wrap/);
  });

  it('Confirm 버튼 클릭 → api.confirmImport 호출, 결과 화면 렌더', async () => {
    renderLegacy();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));

    await screen.findByTestId('confirm-btn');
    fireEvent.click(screen.getByTestId('confirm-btn'));

    await waitFor(() => expect(api.confirmImport).toHaveBeenCalledTimes(1));

    // trace_id가 전달되었는지 확인
    expect(api.confirmImport).toHaveBeenCalledWith(
      expect.any(File),
      'strict',
      'tr_abc123',
      expect.any(Object),
    );

    // 결과 카운트 렌더
    const resultCounts = await screen.findByTestId('result-counts');
    expect(resultCounts.textContent).toContain('3'); // inserted
  });

  it('failure_csv_url 있으면 CSV 다운로드 링크 표시', async () => {
    api.confirmImport.mockResolvedValueOnce({
      ...CONFIRM_OK,
      failure_csv_url: '/api/import/classified/failure-csv/tr_abc123',
    });

    renderLegacy();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));
    await screen.findByTestId('confirm-btn');
    fireEvent.click(screen.getByTestId('confirm-btn'));

    const link = await screen.findByTestId('csv-download');
    expect(link.href).toContain('failure-csv');
  });

  it('preview ok=false → Confirm 버튼 비활성', async () => {
    api.previewImport.mockResolvedValueOnce(PREVIEW_WITH_ERRORS);

    renderLegacy();
    fireEvent.drop(screen.getByLabelText('파일 업로드 영역'), {
      dataTransfer: { files: [makeFile()] },
    });
    fireEvent.click(screen.getByTestId('preview-btn'));

    const confirmBtn = await screen.findByTestId('confirm-btn');
    expect(confirmBtn.disabled).toBe(true);
  });

  it('모드 lenient으로 전환 후 Preview → api에 lenient 전달', async () => {
    renderLegacy();
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
