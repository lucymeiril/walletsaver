/**
 * ExternalExportPanel.test.jsx
 * crawler-admin 외부 분류 내보내기 패널 테스트.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

// ── api/client 모킹 ──────────────────────────────────────────────────────────
vi.mock('../../../api/client', () => ({
  api: {
    getRuns: vi.fn().mockResolvedValue({
      items: [
        { run_id: 'run-001', plugin_name: 'emart', started_at: '2025-06-01T10:00:00Z' },
        { run_id: 'run-002', plugin_name: 'homeplus', started_at: '2025-06-02T11:00:00Z' },
      ],
    }),
    getRecentExports: vi.fn().mockResolvedValue([
      {
        export_id: 'exp-abc',
        created_at: '2025-06-01T12:00:00Z',
        miss_rows: 42,
      },
    ]),
    triggerRawBatchExport: vi.fn().mockResolvedValue({
      export_id: 'exp-new',
      miss_rows: 10,
      file_sha256s: { 'raw_products.jsonl': 'abcdef' },
    }),
    getRawBatchExportDownloadUrl: vi.fn((id) => `/api/export/raw-batch/${id}/download`),
  },
}));

import { api } from '../../../api/client';
import ExternalExportPanel from '../ExternalExportPanel';

function renderPanel() {
  return render(
    <MemoryRouter>
      <ExternalExportPanel />
    </MemoryRouter>
  );
}

describe('ExternalExportPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getRuns.mockResolvedValue({
      items: [
        { run_id: 'run-001', plugin_name: 'emart', started_at: '2025-06-01T10:00:00Z' },
        { run_id: 'run-002', plugin_name: 'homeplus', started_at: '2025-06-02T11:00:00Z' },
      ],
    });
    api.getRecentExports.mockResolvedValue([
      { export_id: 'exp-abc', created_at: '2025-06-01T12:00:00Z', miss_rows: 42 },
    ]);
    api.triggerRawBatchExport.mockResolvedValue({
      export_id: 'exp-new',
      miss_rows: 10,
      file_sha256s: {},
    });
  });

  // ── 렌더 ──────────────────────────────────────────────────────────────────
  it('renders panel with title and step indicator', async () => {
    renderPanel();
    expect(screen.getByTestId('external-export-panel')).toBeInTheDocument();
    expect(await screen.findByText('외부 분류 내보내기')).toBeInTheDocument();
    expect(screen.getByText('raw batch 선택')).toBeInTheDocument();
    expect(screen.getByText('옵션 설정')).toBeInTheDocument();
    expect(screen.getByText('내보내기')).toBeInTheDocument();
  });

  it('shows manual link to docs', async () => {
    renderPanel();
    const link = await screen.findByText(/외부 분류 운영 매뉴얼/);
    expect(link).toBeInTheDocument();
  });

  it('shows desc hint about weekly recommendation', async () => {
    renderPanel();
    expect(await screen.findByText(/매주 1회 권장/)).toBeInTheDocument();
  });

  // ── batch 체크박스 ─────────────────────────────────────────────────────────
  it('renders batch checkboxes for recent runs', async () => {
    renderPanel();
    const cb1 = await screen.findByTestId('raw-batch-checkbox-run-001');
    const cb2 = await screen.findByTestId('raw-batch-checkbox-run-002');
    expect(cb1).toBeInTheDocument();
    expect(cb2).toBeInTheDocument();
  });

  it('checking a batch checkbox updates selection count', async () => {
    renderPanel();
    const cb1 = await screen.findByTestId('raw-batch-checkbox-run-001');
    fireEvent.click(cb1);
    await waitFor(() => {
      const panel = screen.getByTestId('external-export-panel');
      expect(panel.textContent).toMatch(/선택된 batch/);
      expect(panel.textContent).toMatch(/1개/);
    });
  });

  it('manual batch ID input is rendered', async () => {
    renderPanel();
    expect(await screen.findByTestId('manual-batch-ids')).toBeInTheDocument();
  });

  it('manual batch IDs are collected', async () => {
    renderPanel();
    const textarea = await screen.findByTestId('manual-batch-ids');
    fireEvent.change(textarea, { target: { value: 'batch-x\nbatch-y' } });
    await waitFor(() => {
      const panel = screen.getByTestId('external-export-panel');
      expect(panel.textContent).toMatch(/선택된 batch/);
      expect(panel.textContent).toMatch(/2개/);
    });
  });

  // ── Step 전환 ──────────────────────────────────────────────────────────────
  it('clicking 다음 without selection shows toast error', async () => {
    renderPanel();
    await screen.findByText('raw batch 선택');
    const nextBtn = screen.getByText('다음: 옵션 설정 →');
    fireEvent.click(nextBtn);
    expect(await screen.findByTestId('export-toast')).toBeInTheDocument();
    expect(screen.getByTestId('export-toast')).toHaveTextContent('하나 이상 선택');
  });

  it('selecting a batch and clicking 다음 goes to step 2', async () => {
    renderPanel();
    const cb1 = await screen.findByTestId('raw-batch-checkbox-run-001');
    fireEvent.click(cb1);
    fireEvent.click(screen.getByText('다음: 옵션 설정 →'));
    expect(await screen.findByTestId('export-trigger-btn')).toBeInTheDocument();
  });

  // ── export API 모킹 ────────────────────────────────────────────────────────
  it('clicking export button calls triggerRawBatchExport', async () => {
    renderPanel();
    const cb1 = await screen.findByTestId('raw-batch-checkbox-run-001');
    fireEvent.click(cb1);
    fireEvent.click(screen.getByText('다음: 옵션 설정 →'));
    const exportBtn = await screen.findByTestId('export-trigger-btn');
    fireEvent.click(exportBtn);
    await waitFor(() => expect(api.triggerRawBatchExport).toHaveBeenCalledTimes(1));
    expect(api.triggerRawBatchExport).toHaveBeenCalledWith(
      expect.objectContaining({
        raw_batch_ids: expect.arrayContaining(['run-001']),
        include_matched: false,
        format: expect.arrayContaining(['jsonl', 'csv']),
      })
    );
  });

  // ── 결과 박스 ──────────────────────────────────────────────────────────────
  it('shows export result panel after successful export', async () => {
    renderPanel();
    const cb1 = await screen.findByTestId('raw-batch-checkbox-run-001');
    fireEvent.click(cb1);
    fireEvent.click(screen.getByText('다음: 옵션 설정 →'));
    fireEvent.click(await screen.findByTestId('export-trigger-btn'));
    expect(await screen.findByTestId('export-result-panel')).toBeInTheDocument();
    expect(screen.getByTestId('download-zip-btn')).toBeInTheDocument();
  });

  it('result panel shows LLM guide text', async () => {
    renderPanel();
    const cb1 = await screen.findByTestId('raw-batch-checkbox-run-001');
    fireEvent.click(cb1);
    fireEvent.click(screen.getByText('다음: 옵션 설정 →'));
    fireEvent.click(await screen.findByTestId('export-trigger-btn'));
    expect(await screen.findByText(/외부 LLM/)).toBeInTheDocument();
  });

  // ── 이력 테이블 ────────────────────────────────────────────────────────────
  it('renders export history table', async () => {
    renderPanel();
    expect(await screen.findByTestId('export-history-section')).toBeInTheDocument();
    // history item export_id shown
    expect(await screen.findByText('exp-abc')).toBeInTheDocument();
  });

  it('history table shows miss_rows', async () => {
    renderPanel();
    expect(await screen.findByText('42')).toBeInTheDocument();
  });

  // ── format 옵션 ────────────────────────────────────────────────────────────
  it('format checkboxes default to jsonl and csv both on', async () => {
    renderPanel();
    const cb1 = await screen.findByTestId('raw-batch-checkbox-run-001');
    fireEvent.click(cb1);
    fireEvent.click(screen.getByText('다음: 옵션 설정 →'));
    const fmtJsonl = await screen.findByTestId('format-jsonl');
    const fmtCsv = screen.getByTestId('format-csv');
    expect(fmtJsonl).toBeChecked();
    expect(fmtCsv).toBeChecked();
  });

  it('include_matched checkbox defaults to unchecked', async () => {
    renderPanel();
    const cb1 = await screen.findByTestId('raw-batch-checkbox-run-001');
    fireEvent.click(cb1);
    fireEvent.click(screen.getByText('다음: 옵션 설정 →'));
    const incl = await screen.findByTestId('include-matched');
    expect(incl).not.toBeChecked();
  });
});
