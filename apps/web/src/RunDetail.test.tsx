import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { RunDetail } from './RunDetail';
import { api } from './api';
import type { Registry, Run } from './types';

vi.mock('./api', async importOriginal => ({ ...await importOriginal<typeof import('./api')>(), api: vi.fn() }));

class Stream extends EventTarget {
  static latest: Stream;
  onerror = null;
  close = vi.fn();
  constructor() { super(); Stream.latest = this; }
  progress(value: Run) { this.dispatchEvent(new MessageEvent('progress', { data: JSON.stringify(value) })); }
}
function deferred() {
  let resolve!: (value: Run) => void;
  const promise = new Promise<Run>(r => { resolve = r; });
  return { promise, resolve };
}
function snapshot(status: string, revision: number): Run {
  return { id: 'fixture', revision, status, model: { name: 'Fixture', backend: 'mock' }, total: 1, completed: status === 'completed' ? 1 : 0,
    correct: 0, accuracy: 0, micro_accuracy: 0, completion_rate: 0, by_origin: {}, by_category: {}, by_difficulty: [], status_counts: {},
    latency_p50: null, latency_p95: null, provisional: status !== 'completed', warnings: [], results: [] } as unknown as Run;
}
const registry = { categories: [] } as unknown as Registry;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

it('keeps completion when an older initial detail response arrives after the terminal event', async () => {
  vi.stubGlobal('EventSource', Stream);
  const initial = deferred();
  vi.mocked(api).mockReturnValueOnce(initial.promise).mockResolvedValue(snapshot('completed', 3));
  render(<RunDetail id="fixture" registry={registry} onError={vi.fn()} refresh={vi.fn().mockResolvedValue(undefined)}/>);
  await act(async () => Stream.latest.progress(snapshot('completed', 3)));
  expect(screen.getByText('完了', { exact: true })).toBeVisible();
  await act(async () => initial.resolve(snapshot('running', 1)));
  expect(screen.getByText('完了', { exact: true })).toBeVisible();
  expect(Stream.latest.close).toHaveBeenCalled();
});

it('keeps completion when a resume response fetch arrives late', async () => {
  vi.stubGlobal('EventSource', Stream);
  const resumed = deferred();
  vi.mocked(api).mockResolvedValueOnce(snapshot('paused', 2)).mockResolvedValueOnce({}).mockReturnValueOnce(resumed.promise).mockResolvedValue(snapshot('completed', 4));
  render(<RunDetail id="fixture" registry={registry} onError={vi.fn()} refresh={vi.fn().mockResolvedValue(undefined)}/>);
  await act(async () => {});
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '再開' })));
  await act(async () => Stream.latest.progress(snapshot('completed', 4)));
  await act(async () => resumed.resolve(snapshot('queued', 3)));
  expect(screen.getByText('完了', { exact: true })).toBeVisible();
});
