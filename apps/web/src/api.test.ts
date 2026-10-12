import { afterEach, expect, it, vi } from 'vitest';
import { api, pct, seconds } from './api';
afterEach(() => vi.unstubAllGlobals());
it('preserves unavailable metrics and reports server errors', async () => {
  expect(pct(null)).toBe('N/A'); expect(seconds(null)).toBe('N/A'); expect(pct(0)).toBe('0.0%');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: '固定問題不足' }) }));
  await expect(api('/sets', {})).rejects.toThrow('固定問題不足');
});
it('sends mutation requests as JSON and returns typed data', async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ run_ids: ['run'] }) });
  vi.stubGlobal('fetch', fetcher);
  expect(await api('/runs', { set_id: 'set' })).toEqual({ run_ids: ['run'] });
  expect(fetcher).toHaveBeenCalledWith('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"set_id":"set"}' });
});
