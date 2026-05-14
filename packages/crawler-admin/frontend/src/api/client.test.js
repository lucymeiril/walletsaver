import { describe, expect, it, vi, afterEach } from 'vitest';
import { api } from './client';

describe('AI provider proxy client', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads providers through crawler-admin same-origin proxy only', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ providers: [], count: 0 }),
    });

    await api.getAiProviders('http://localhost:8003');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/ai-export/providers?ai_admin_base_url=http%3A%2F%2Flocalhost%3A8003');
    expect(url).not.toContain('http://localhost:8003' + '/api/providers');
  });
});
