import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import { RunBatch } from './RunBatch';
vi.mock('./api', async original => ({ ...await original<typeof import('./api')>(), api: vi.fn() }));
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });
it('shows successful model progress when another request fails', async () => {
  vi.mocked(api).mockImplementation(path => path.includes('/good?') ? Promise.resolve({ id: 'good', model: { name: 'Good model' }, status: 'running', completed: 2, total: 5 }) : Promise.reject(new Error('offline')));
  render(<RunBatch ids={['good', 'bad']} selected="good" open={vi.fn()} onError={vi.fn()}/>);
  expect(await screen.findByText('Good model')).toBeVisible();
  expect(screen.getByText('2 / 5')).toBeVisible();
  expect(screen.getByText('取得失敗 · 再接続中')).toBeVisible();
});

it('does not keep retrying deleted runs while other models continue updating', async () => {
  vi.useFakeTimers();
  vi.mocked(api).mockImplementation(path => path.includes('/good?') ? Promise.resolve({ id: 'good', model: { name: 'Good model' }, status: 'running', completed: 2, total: 5 }) : Promise.reject(new ApiError('missing', 404)));
  render(<RunBatch ids={['good', 'deleted']} selected="good" open={vi.fn()} onError={vi.fn()}/>);
  await act(async () => {});
  expect(screen.getByText('削除済み・見つかりません')).toBeVisible();
  expect(screen.getByRole('button', { name: 'このモデルの詳細' })).toBeDisabled();
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(vi.mocked(api).mock.calls.filter(([path]) => path.includes('/deleted?'))).toHaveLength(1);
  expect(vi.mocked(api).mock.calls.filter(([path]) => path.includes('/good?'))).toHaveLength(2);
});

it('updates a responsive model while another model request remains pending', async () => {
  vi.useFakeTimers();
  let completed = 1;
  vi.mocked(api).mockImplementation(path => path.includes('/good?') ? Promise.resolve({ id: 'good', model: { name: 'Good model' }, status: 'running', completed: completed++, total: 5 }) : new Promise(() => {}));
  render(<RunBatch ids={['good', 'slow']} selected="good" open={vi.fn()} onError={vi.fn()}/>);
  await act(async () => {});
  expect(screen.getByText('Good model')).toBeVisible();
  expect(screen.getByText('1 / 5')).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.getByText('2 / 5')).toBeVisible();
  expect(vi.mocked(api).mock.calls.filter(([path]) => path.includes('/slow?'))).toHaveLength(1);
});
