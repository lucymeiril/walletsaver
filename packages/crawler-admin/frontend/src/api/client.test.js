import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';
import { getNextCronRuns, cronToHuman } from '../pages/Schedule/Schedule';

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

describe('weekly schedule UTC and Unix weekday boundary', () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
  it.each([
    ['0 7 * * 1', '2026-10-05T07:00:00.000Z'],
    ['0 7 * * 0', '2026-10-04T07:00:00.000Z'],
    ['0 7 * * 7', '2026-10-04T07:00:00.000Z'],
    ['0 7 6 * 1', '2026-10-05T07:00:00.000Z'],
  ])('previews literal %s in UTC regardless of browser timezone', (cron, expected) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-03T12:00:00Z'));
    expect(getNextCronRuns(cron, 1)[0].toISOString()).toBe(expected);
    expect(cronToHuman('0 7 * * 1')).toContain('월요일');
  });
  it('keeps stored Unix expression unchanged in the existing create request', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 201,
      json: async () => ({ id: 'weekly', plugin_name: 'lottemart', cron_expr: '0 7 * * 1', enabled: true }) });
    await api.createSchedule({ crawler_name: 'lottemart', cron: '0 7 * * 1' });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      plugin_name: 'lottemart', cron_expr: '0 7 * * 1', enabled: true,
    });
  });
});
