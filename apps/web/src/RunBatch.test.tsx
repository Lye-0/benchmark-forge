import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from './api';
import { RunBatch } from './RunBatch';
vi.mock('./api', async original => ({ ...await original<typeof import('./api')>(), api: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it('shows successful model progress when another request fails', async () => {
  vi.mocked(api).mockImplementation(path => path.includes('/good?') ? Promise.resolve({ id: 'good', model: { name: 'Good model' }, status: 'running', completed: 2, total: 5 }) : Promise.reject(new Error('offline')));
  render(<RunBatch ids={['good', 'bad']} selected="good" open={vi.fn()} onError={vi.fn()}/>);
  expect(await screen.findByText('Good model')).toBeVisible();
  expect(screen.getByText('2 / 5')).toBeVisible();
  expect(screen.getByText('取得失敗 · 再接続中')).toBeVisible();
});
