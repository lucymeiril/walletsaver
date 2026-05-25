import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ImportClassifiedPage from '../ImportClassifiedPage';

// Mock CSS modules
vi.mock('../ImportClassifiedPage.module.css', () => ({
  default: new Proxy({}, { get: (_, k) => k }),
}));
vi.mock('../../../components/ImportDiffTable', () => ({ default: () => <div data-testid="diff-table" /> }));
vi.mock('../../../components/ImportConflictList', () => ({ default: () => <div data-testid="conflict-list" /> }));

const mockPreviewBundleImport = vi.fn();
const mockConfirmBundleImport = vi.fn();

vi.mock('../../../api/client', () => ({
  api: {
    previewImport: vi.fn(),
    confirmImport: vi.fn(),
    previewBundleImport: (...args) => mockPreviewBundleImport(...args),
    confirmBundleImport: (...args) => mockConfirmBundleImport(...args),
    getBundleFailureCsvUrl: (batchId) => `/api/import/bundle/${batchId}/failures.csv`,
  },
}));

const makeFile = (name, content = '{}') =>
  new File([content], name, { type: 'application/octet-stream' });

describe('ImportClassifiedPage — Bundle Tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders three bundle file slots on Bundle tab', () => {
    render(<ImportClassifiedPage />);
    // Default tab should be bundle
    expect(screen.getByTestId('tab-bundle')).toBeTruthy();
    expect(screen.getByTestId('slot-matching')).toBeTruthy();
    expect(screen.getByTestId('slot-taxonomy')).toBeTruthy();
    expect(screen.getByTestId('slot-products')).toBeTruthy();
  });

  it('renders bundle-preview-btn and it is disabled when no files selected', () => {
    render(<ImportClassifiedPage />);
    const previewBtn = screen.getByTestId('bundle-preview-btn');
    expect(previewBtn).toBeTruthy();
    expect(previewBtn.disabled).toBe(true);
  });

  it('enables bundle-preview-btn when a file is added to matching slot', async () => {
    render(<ImportClassifiedPage />);
    const slot = screen.getByTestId('slot-matching');
    const input = slot.querySelector('input[type="file"]');
    expect(input).toBeTruthy();

    const file = makeFile('matching_updates.jsonl', '{"match_key":"k1","category_id":1}\n');
    await userEvent.upload(input, file);

    const previewBtn = screen.getByTestId('bundle-preview-btn');
    await waitFor(() => expect(previewBtn.disabled).toBe(false));
  });

  it('calls previewBundleImport and shows preview sections', async () => {
    mockPreviewBundleImport.mockResolvedValue({
      ok: true,
      batch_id: 'imp-20250101000000-abcd1234',
      matching: { to_add: 5, to_update: 2, conflicts: [], pending_human: 1 },
      taxonomy: { new_categories: 3, new_keywords: 7, merges: [], errors: [] },
      products: { to_add: 4, skipped_no_match: 1, errors: [] },
    });

    render(<ImportClassifiedPage />);
    const slot = screen.getByTestId('slot-matching');
    const input = slot.querySelector('input[type="file"]');
    const file = makeFile('matching_updates.jsonl', '{"match_key":"k1","category_id":1}\n');
    await userEvent.upload(input, file);

    const previewBtn = await screen.findByTestId('bundle-preview-btn');
    await userEvent.click(previewBtn);

    await waitFor(() => {
      expect(mockPreviewBundleImport).toHaveBeenCalledTimes(1);
    });

    // After preview step, confirm button should appear
    await waitFor(() => {
      expect(screen.getByTestId('bundle-confirm-btn')).toBeTruthy();
    });
  });

  it('calls confirmBundleImport and shows bundle-result-summary', async () => {
    mockPreviewBundleImport.mockResolvedValue({
      ok: true,
      batch_id: 'imp-20250101000000-abcd1234',
      matching: { to_add: 1, to_update: 0, conflicts: [], pending_human: 0 },
      taxonomy: { new_categories: 0, new_keywords: 0, merges: [], errors: [] },
      products: { to_add: 0, skipped_no_match: 0, errors: [] },
    });

    mockConfirmBundleImport.mockResolvedValue({
      ok: true,
      batch_id: 'imp-20250101000000-abcd1234',
      idempotent: false,
      matching_inserted: 1,
      matching_updated: 0,
      matching_conflicts: 0,
      taxonomy_categories_added: 0,
      taxonomy_keywords_added: 0,
      products_added: 0,
      products_skipped: 0,
      failure_csv_url: null,
    });

    render(<ImportClassifiedPage />);
    const slot = screen.getByTestId('slot-matching');
    const input = slot.querySelector('input[type="file"]');
    const file = makeFile('matching_updates.jsonl', '{"match_key":"k1","category_id":1}\n');
    await userEvent.upload(input, file);

    await userEvent.click(screen.getByTestId('bundle-preview-btn'));
    await waitFor(() => screen.getByTestId('bundle-confirm-btn'));

    await userEvent.click(screen.getByTestId('bundle-confirm-btn'));
    await waitFor(() => {
      expect(screen.getByTestId('bundle-result-summary')).toBeTruthy();
    });

    expect(mockConfirmBundleImport).toHaveBeenCalledTimes(1);
  });

  it('shows legacy tab content when Legacy tab is clicked', async () => {
    render(<ImportClassifiedPage />);
    const legacyTab = screen.getByTestId('tab-legacy');
    await userEvent.click(legacyTab);

    // Legacy preview button should exist
    expect(screen.getByTestId('preview-btn')).toBeTruthy();
  });
});
