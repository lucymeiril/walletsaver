import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../api/client', () => ({
  api: {
    getIngestions: vi.fn(),
  },
}));

import { api } from '../../../api/client';
import useAdminStore from '../../../stores/adminStore';
import DataReviewPage from '../DataReviewPage';

const INGESTIONS = Array.from({ length: 501 }, (_, index) => ({
  id: index + 1,
  crawler_name: `crawler-${index + 1}`,
  items_count: 1,
  quality_score: 100,
  schema_type: 'DiscountItem',
  status: 'pending',
}));

beforeEach(() => {
  vi.clearAllMocks();
  useAdminStore.setState({
    ingestions: [],
    ingestionsLoading: false,
    ingestionsError: null,
  });
  api.getIngestions.mockImplementation(async ({ limit, offset }) => ({
    total: INGESTIONS.length,
    items: INGESTIONS.slice(offset, offset + limit),
  }));
});

describe('DataReviewPage pagination', () => {
  it('loads every ingestion batch and exposes pages beyond the API first page', async () => {
    render(<DataReviewPage />);

    expect(await screen.findByText('501건 중 1–10')).toBeInTheDocument();
    expect(api.getIngestions).toHaveBeenNthCalledWith(1, { limit: 500, offset: 0 });
    expect(api.getIngestions).toHaveBeenNthCalledWith(2, { limit: 500, offset: 500 });

    fireEvent.click(screen.getByRole('button', { name: '»' }));

    await waitFor(() => {
      expect(screen.getByText('crawler-501')).toBeInTheDocument();
      expect(screen.getByText('501건 중 501–501')).toBeInTheDocument();
    });
  });
});
