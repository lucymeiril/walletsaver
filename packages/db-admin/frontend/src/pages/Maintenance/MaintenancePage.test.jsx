import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MaintenancePage from './MaintenancePage';

vi.mock('../../api/client', () => ({
  api: {
    maintenancePurge: vi.fn(),
    maintenanceMigrate: vi.fn(),
    maintenanceIntegrity: vi.fn(),
  },
}));

import { api } from '../../api/client';

const INTEGRITY_SAMPLE = {
  generated_at: '2024-01-02T03:04:05',
  null: { products_without_category: 3, products_without_name: 1 },
  duplicates: { products: 2, samples: [{ name: '우유', source_type: 'emart', count: 2 }] },
  orphan_fk: { product_keywords_without_product: 0, product_keywords_without_keyword: 0 },
  issue_total: 6,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.maintenanceIntegrity.mockResolvedValue(INTEGRITY_SAMPLE);
  api.maintenancePurge.mockResolvedValue({
    action: 'maintenance.purge',
    scope: 'raw',
    deleted: { pending_ingestions: 5, crawl_logs: 2 },
    total: 7,
  });
  api.maintenanceMigrate.mockResolvedValue({
    action: 'maintenance.migrate',
    revision: 'head',
    returncode: 0,
    stdout: 'INFO  [alembic.runtime.migration] Running upgrade -> abc123',
    stderr: '',
  });
});

describe('MaintenancePage', () => {
  it('renders three cards and loads integrity on mount', async () => {
    render(<MaintenancePage />);
    await waitFor(() => expect(api.maintenanceIntegrity).toHaveBeenCalled());
    expect(screen.getByText(/DB 비우기/)).toBeTruthy();
    expect(screen.getByText(/스키마 마이그레이션/)).toBeTruthy();
    expect(screen.getByText(/이상 데이터 검토/)).toBeTruthy();
    expect(await screen.findByText('카테고리 없음: 3')).toBeTruthy();
  });

  it('purge button disabled until confirm string matches', async () => {
    render(<MaintenancePage />);
    fireEvent.click(screen.getByText(/비우기 시작/));
    const confirmInput = screen.getByLabelText('확인 문자열');
    const runBtn = screen.getByText(/즉시 비우기/);
    expect(runBtn.disabled).toBe(true);
    fireEvent.change(confirmInput, { target: { value: 'wrong' } });
    expect(runBtn.disabled).toBe(true);
    fireEvent.change(confirmInput, { target: { value: 'PURGE RAW' } });
    expect(runBtn.disabled).toBe(false);
    fireEvent.click(runBtn);
    await waitFor(() => expect(api.maintenancePurge).toHaveBeenCalledWith('raw', ''));
    expect(await screen.findByText(/7/)).toBeTruthy();
  });

  it('alembic migrate button triggers api call', async () => {
    render(<MaintenancePage />);
    fireEvent.click(screen.getByText(/alembic upgrade/));
    await waitFor(() => expect(api.maintenanceMigrate).toHaveBeenCalledWith('head'));
    expect(await screen.findByText(/Running upgrade/)).toBeTruthy();
  });
});
