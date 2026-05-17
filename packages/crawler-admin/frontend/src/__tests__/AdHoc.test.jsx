import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/client', () => ({
  api: {
    getOrchestratorPlugins: vi.fn().mockResolvedValue({
      plugins: [{ name: 'emart', display_name: '이마트' }, { name: 'homeplus', display_name: '홈플러스' }],
    }),
    runAdHoc: vi.fn().mockResolvedValue({
      request_id: 'req_xyz',
      request: { result_preview: { status: 'success', items_found: 2, items_saved: 2, errors: [] } },
    }),
  },
}));

import { api } from '../api/client';
import AdHoc from '../pages/AdHoc/AdHoc';

describe('AdHoc page', () => {
  beforeEach(() => {
    api.runAdHoc.mockClear();
  });

  it('renders form with plugin select and search input', async () => {
    render(<MemoryRouter><AdHoc /></MemoryRouter>);
    expect(await screen.findByText('Ad-hoc 수집')).toBeInTheDocument();
    expect(screen.getByLabelText('검색어')).toBeInTheDocument();
    expect(screen.getByLabelText('플러그인 선택')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '실행' })).toBeInTheDocument();
  });

  it('submit button calls runAdHoc API', async () => {
    render(<MemoryRouter><AdHoc /></MemoryRouter>);
    await waitFor(() => expect(screen.getByLabelText('플러그인 선택').value).toBe('emart'));
    fireEvent.change(screen.getByLabelText('검색어'), { target: { value: '우유' } });
    fireEvent.click(screen.getByRole('button', { name: '실행' }));
    await waitFor(() => expect(api.runAdHoc).toHaveBeenCalledTimes(1));
    expect(api.runAdHoc).toHaveBeenCalledWith(expect.objectContaining({
      plugin_name: 'emart',
      search_query: '우유',
    }));
  });
});

