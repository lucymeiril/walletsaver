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

describe('bounded Lotte run client', () => {
  afterEach(() => { vi.restoreAllMocks(); });
  it.each([undefined, { source_url: 'https://lottemartzetta.com/products/OS8801114119426/details' }])('retains broad default or sends only source_url (%s)', async (options) => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: 'running' }) });
    await api.runCrawler('lottemart', options);
    const [url, request] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/crawlers/lottemart/run');
    expect(request.method).toBe('POST');
    if (options) expect(JSON.parse(request.body)).toEqual(options);
    else expect(request.body).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
