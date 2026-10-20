import { expect, it } from 'vitest';
import { ProgressWatch, waitForRuns, type RunProgress } from '../e2e/run-progress';
const row = (id: string, status: string, completed: number): RunProgress => ({ id, status, completed, total: 100, revision: completed });

it('waits for both sequential models while a resumed run queues behind the other model', () => {
  const watch = new ProgressWatch(['a', 'b'], 0);
  expect(watch.observe([row('a', 'queued', 2), row('b', 'running', 1)], 0)).toBe(false);
  expect(watch.observe([row('a', 'queued', 2), row('b', 'running', 75)], 10000)).toBe(false);
  expect(watch.observe([row('a', 'running', 59), row('b', 'completed', 100)], 20000)).toBe(false);
  expect(watch.observe([row('a', 'completed', 100), row('b', 'completed', 100)], 30000)).toBe(true);
});

it('prepares UI fixtures when the second model stays queued beyond the UI deadline', async () => {
  let clock = 0;
  const snapshots = [
    [row('first', 'running', 0), row('second', 'queued', 0)],
    [row('first', 'running', 50), row('second', 'queued', 0)],
    [row('first', 'completed', 100), row('second', 'running', 0)],
    [row('first', 'completed', 100), row('second', 'completed', 100)],
  ];
  await waitForRuns(new ProgressWatch(['first', 'second'], 0, 15000, 30000), async () => {
    const snapshot = snapshots.shift();
    if (!snapshot) throw new Error('Unexpected extra progress read');
    return snapshot;
  }, () => clock, async () => { clock += 6000; });
  expect(clock).toBe(18000);
  expect(snapshots).toHaveLength(0);
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

it('recovers from one slow progress request without treating it as a run failure', async () => {
  const { waitForRuns } = await import('../e2e/run-progress');
  let clock = 0, calls = 0;
  const timeout = Object.assign(new Error('fixture timeout'), { name: 'TimeoutError' });
  await waitForRuns(new ProgressWatch(['a'], 0), async () => {
    calls++;
    if (calls === 2) { clock += 5000; throw timeout; }
    return [row('a', calls === 3 ? 'completed' : 'running', calls === 3 ? 100 : 5)];
  }, () => clock, async ms => { clock += ms; });
  expect(calls).toBe(3);
});

it('fails on persistent transport timeouts and does not retry HTTP failures', async () => {
  const { waitForRuns } = await import('../e2e/run-progress');
  let clock = 0;
  await expect(waitForRuns(new ProgressWatch(['a'], 0), async () => {
    clock += 5000;
    throw Object.assign(new Error('fixture timeout'), { name: 'TimeoutError' });
  }, () => clock, async ms => { clock += ms; })).rejects.toThrow('stopped making progress');
  await expect(waitForRuns(new ProgressWatch(['a'], 0), async () => {
    throw new Error('HTTP 500');
  }, () => 0)).rejects.toThrow('HTTP 500');
});


it('waits for a durable automatic pause without accepting completion or cancellation', () => {
  const watch = new ProgressWatch(['a'], 0, 15000, 30000, 'paused');
  expect(watch.observe([row('a', 'running', 0)], 0)).toBe(false);
  expect(watch.observe([row('a', 'running', 1)], 6000)).toBe(false);
  expect(watch.observe([row('a', 'paused', 1)], 7000)).toBe(true);
  for (const status of ['completed', 'cancelled']) {
    expect(() => new ProgressWatch(['a'], 0, 15000, 30000, 'paused').observe([row('a', status, 100)], 1)).toThrow('Unexpected run state');
  }
  const stalled = new ProgressWatch(['a'], 0, 15000, 30000, 'paused');
  stalled.observe([row('a', 'running', 1)], 0);
  expect(() => stalled.observe([row('a', 'running', 1)], 15000)).toThrow('stopped making progress');
});
