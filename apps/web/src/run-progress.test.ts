import { expect, it } from 'vitest';
import { ProgressWatch, type RunProgress } from '../e2e/run-progress';
const row = (id: string, status: string, completed: number): RunProgress => ({ id, status, completed, total: 100, revision: completed });

it('waits for both sequential models while a resumed run queues behind the other model', () => {
  const watch = new ProgressWatch(['a', 'b'], 0);
  expect(watch.observe([row('a', 'queued', 2), row('b', 'running', 1)], 0)).toBe(false);
  expect(watch.observe([row('a', 'queued', 2), row('b', 'running', 75)], 10000)).toBe(false);
  expect(watch.observe([row('a', 'running', 59), row('b', 'completed', 100)], 20000)).toBe(false);
  expect(watch.observe([row('a', 'completed', 100), row('b', 'completed', 100)], 30000)).toBe(true);
});

it('fails on a stalled selected queue even if unrelated runs advance', () => {
  const watch = new ProgressWatch(['a'], 0);
  watch.observe([row('a', 'running', 2)], 0);
  expect(() => watch.observe([row('a', 'running', 2), row('other', 'running', 50)], 15000)).toThrow('stopped making progress');
});

it('fails on unexpected pause or an overall deadline despite incremental progress', () => {
  expect(() => new ProgressWatch(['a'], 0).observe([row('a', 'paused', 2)], 1)).toThrow('Unexpected run state');
  const watch = new ProgressWatch(['a'], 0);
  for (let i = 0; i < 12; i++) watch.observe([row('a', 'running', i)], i * 10000);
  expect(() => watch.observe([row('a', 'running', 12)], 120000)).toThrow('deadline exceeded');
  expect(() => watch.observe([row('a', 'completed', 100)], 120001)).toThrow('deadline exceeded');
});
