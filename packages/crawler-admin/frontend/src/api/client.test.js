import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';

describe('external classification export client', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('posts explicit PendingIngestion ids to crawler-admin export endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ export_id: 'exp-test', source_ingestions: [11, 12] }),
    });

    await api.triggerRawBatchExport({
      ingestion_ids: [11, 12],
      include_matched: false,
      format: ['jsonl'],
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/export/raw-batch');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({
      ingestion_ids: [11, 12],
      include_matched: false,
      format: ['jsonl'],
    });
  });
});
