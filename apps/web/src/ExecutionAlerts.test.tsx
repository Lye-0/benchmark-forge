import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ExecutionAlerts } from './ExecutionAlerts';
import { api } from './api';
vi.mock('./api', () => ({ api: vi.fn() }));
const block = { id: 'blocked', model_name: 'Ollama test', detected_at: 'now', reason: 'Ollamaに接続できません' };
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });
it('keeps a durable stop visible after dismissal and never resumes automatically', async () => {
  vi.useFakeTimers();
  vi.mocked(api).mockResolvedValue([block]);
  render(<ExecutionAlerts onChanged={vi.fn()}/>);
  await act(async () => {});
  expect(screen.getByRole('dialog')).toHaveTextContent('Ollamaに接続できません');
  fireEvent.click(screen.getByRole('button', { name: '閉じる' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('モデルを実行できず、1件の評価が一時停止しています。')).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.every(([path]) => path === '/execution-blocks')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '停止理由を確認' }));
  expect(screen.getByRole('dialog')).toBeVisible();
});
it('retains the popup after a failed reconnect and closes it after a successful resume', async () => {
  let stopped = true;
  let available = false;
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/execution-blocks') return stopped ? [block] : [];
    if (!available) throw new Error('接続できません');
    stopped = false; return {};
  });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  render(<ExecutionAlerts onChanged={onChanged}/>);
  await act(async () => {});
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '接続を確認して再開' })));
  expect(screen.getByRole('dialog')).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent('接続できません');
  available = true;
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '接続を確認して再開' })));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(onChanged).toHaveBeenCalledOnce();
});
it('shows start failures without claiming a run was started', async () => {
  vi.mocked(api).mockResolvedValue([]);
  render(<ExecutionAlerts onChanged={vi.fn()}/>);
  await act(async () => {});
  act(() => window.dispatchEvent(new CustomEvent('forge-start-unavailable', { detail: '指定モデルが見つかりません' })));
  expect(screen.getByRole('dialog', { name: '評価を開始できません' })).toHaveTextContent('指定モデルが見つかりません');
  expect(screen.queryByRole('button', { name: '接続を確認して再開' })).not.toBeInTheDocument();
});
