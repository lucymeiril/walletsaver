import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../api/client', () => ({
  api: {
    getIngestions: vi.fn(),
    getRecentExports: vi.fn(),
    triggerRawBatchExport: vi.fn(),
    getRawBatchExportDownloadUrl: vi.fn((id) => `/api/export/raw-batch/${id}/download`),
  },
}));

import { api } from '../../../api/client';
import ExternalExportPanel from '../ExternalExportPanel';

const INGESTIONS = {
  items: [
    { id: 11, crawler_name: 'emart', items_count: 20, status: 'pending', crawled_at: '2026-08-24T10:00:00Z' },
    { id: 12, crawler_name: 'homeplus', items_count: 15, status: 'crawler_approved', crawled_at: '2026-08-24T11:00:00Z' },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getIngestions.mockResolvedValue(INGESTIONS);
  api.getRecentExports.mockResolvedValue({
    exports: [
      {
        export_id: 'exp-20260824120000-12345678',
        created_at: '2026-08-24T12:00:00Z',
        source_ingestions: [11],
        miss_rows: 7,
      },
    ],
  });
  api.triggerRawBatchExport.mockResolvedValue({
    export_id: 'exp-20260824130000-abcdef12',
    source_ingestions: [11],
    miss_rows: 7,
    exported_rows: 7,
  });
});

describe('ExternalExportPanel', () => {
  it('loads current pending ingestions instead of orchestrator run ids', async () => {
    render(<ExternalExportPanel />);

    expect(screen.getByTestId('external-export-panel')).toBeInTheDocument();
    expect(await screen.findByTestId('ingestion-checkbox-11')).toBeInTheDocument();
    expect(screen.getByTestId('ingestion-checkbox-12')).toBeInTheDocument();
    expect(api.getIngestions).toHaveBeenCalledWith({ limit: 50, offset: 0 });
    expect(screen.getByText(/PendingIngestion ID/)).toBeInTheDocument();
  });

  it('accepts explicit numeric ingestion ids', async () => {
    render(<ExternalExportPanel />);
    const textarea = await screen.findByTestId('manual-ingestion-ids');
    fireEvent.change(textarea, { target: { value: '21, 22' } });
    expect(screen.getByText(/선택된 대기열:/)).toHaveTextContent('2개');
  });

  it('sends ingestion_ids to the export endpoint', async () => {
    render(<ExternalExportPanel />);
    fireEvent.click(await screen.findByTestId('ingestion-checkbox-11'));
    fireEvent.click(screen.getByText('다음: 옵션 설정 →'));
    fireEvent.click(await screen.findByTestId('export-trigger-btn'));

    await waitFor(() => expect(api.triggerRawBatchExport).toHaveBeenCalledTimes(1));
    expect(api.triggerRawBatchExport).toHaveBeenCalledWith({
      ingestion_ids: [11],
      include_matched: false,
      format: ['jsonl', 'csv'],
    });
  });

  it('shows the resulting export and download link', async () => {
    render(<ExternalExportPanel />);
    fireEvent.click(await screen.findByTestId('ingestion-checkbox-11'));
    fireEvent.click(screen.getByText('다음: 옵션 설정 →'));
    fireEvent.click(await screen.findByTestId('export-trigger-btn'));

    expect(await screen.findByTestId('export-result-panel')).toBeInTheDocument();
    expect(screen.getByText('exp-20260824130000-abcdef12')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /ZIP 다운로드/ })).toHaveAttribute(
      'href',
      '/api/export/raw-batch/exp-20260824130000-abcdef12/download',
    );
  });

  it('renders history with source ingestion ids', async () => {
    render(<ExternalExportPanel />);
    expect(await screen.findByText('exp-20260824120000-12345678')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
  });
});
