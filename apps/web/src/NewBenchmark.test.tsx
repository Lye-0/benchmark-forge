import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { NewBenchmark } from './NewBenchmark';
import type { Config, Model, Registry } from './types';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const config: Config = { generator_ids: ['math.linear'], count: 20, seed: 42, difficulty_min: 0, difficulty_max: 100, fixed_ratio: .5, profile: 'preview-quick-v1', custom: false };
const registry: Registry = { categories: [], generator_count: 1, covered_categories: 1, total_categories: 16, difficulty_calibrated: false };
const model: Model = { model_id: 'mock-reference', name: 'Mock', model: 'reference', backend: 'mock', endpoint: '', revision: '1', quantization: 'N/A', temperature: 0, max_tokens: 512, timeout_seconds: 30, capabilities: { available: true, status: 'test-only', reason: 'Mock', test_only: true, live_verified: false, execution_path: 'mock', native_tools: false } };

it('discards a frozen response if settings changed while the request was pending', async () => {
  let resolve!: (value: unknown) => void;
  const pending = new Promise(r => { resolve = r; });
  vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending));
  render(<NewBenchmark registry={registry} models={[model]} presets={[{ id: 'preview-quick-v1', name: 'クイック', description: '', config }]} onCreated={vi.fn()} refresh={vi.fn()} onError={vi.fn()}/>);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '問題セットを確定する' }));
  await user.clear(screen.getByLabelText('問題数'));
  await user.type(screen.getByLabelText('問題数'), '100');
  resolve({ ok: true, json: async () => ({ set_id: 'set-old', set_hash: 'hash-old', count: 20, fixed_count: 10, dynamic_count: 10, warnings: [], duplicate_stats: {}, sample: [] }) });
  await waitFor(() => expect(screen.getByRole('button', { name: '問題セットを確定する' })).toBeEnabled());
  expect(screen.queryByRole('heading', { name: '確定した問題セット' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '選択した1モデルの評価を開始' })).not.toBeInTheDocument();
});

it('rejects out of range or fractional question counts before calling the API', async () => {
  const fetch = vi.fn();
  vi.stubGlobal('fetch', fetch);
  render(<NewBenchmark registry={registry} models={[model]} presets={[{ id: 'preview-quick-v1', name: 'クイック', description: '', config }]} onCreated={vi.fn()} refresh={vi.fn()} onError={vi.fn()}/>);
  const user = userEvent.setup();
  for (const value of ['8001', '1.5']) {
    await user.clear(screen.getByLabelText('問題数'));
    await user.type(screen.getByLabelText('問題数'), value);
    expect(screen.getByRole('button', { name: '問題セットを確定する' })).toBeDisabled();
  }
  expect(fetch).not.toHaveBeenCalled();
});

it('opens created runs without waiting for unrelated history and settings refresh', async () => {
  const onCreated = vi.fn();
  const refresh = vi.fn(() => new Promise<void>(() => {}));
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ set_id: 'set-new', set_hash: 'hash', count: 20, fixed_count: 10, dynamic_count: 10, warnings: [], duplicate_stats: {}, sample: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ run_ids: ['run-a'] }) }));
  render(<NewBenchmark registry={registry} models={[model]} presets={[{ id: 'preview-quick-v1', name: 'クイック', description: '', config }]} onCreated={onCreated} refresh={refresh} onError={vi.fn()}/>);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '問題セットを確定する' }));
  await user.click(await screen.findByRole('button', { name: '選択した1モデルの評価を開始' }));
  expect(onCreated).toHaveBeenCalledWith(['run-a']);
});
