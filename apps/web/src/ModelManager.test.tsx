import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ModelManager } from './ModelManager';
import { api } from './api';

afterEach(() => { cleanup(); vi.clearAllMocks(); });

vi.mock('./api', () => ({ api: vi.fn().mockResolvedValue({}) }));

it('saves local Transformers device and context limit', async () => {
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<ModelManager models={[]} refresh={refresh} onError={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText('モデルID'), { target: { value: 'local-cpu' } });
  fireEvent.change(screen.getByLabelText('表示名'), { target: { value: 'Local CPU' } });
  fireEvent.change(screen.getByLabelText('バックエンド'), { target: { value: 'transformers' } });
  fireEvent.change(screen.getByLabelText('モデルの保存フォルダ（絶対パス）'), { target: { value: '/models/local' } });
  fireEvent.change(screen.getByLabelText(/コンテキスト上限/), { target: { value: '2048' } });
  fireEvent.change(screen.getByLabelText(/推論デバイス/), { target: { value: 'cuda' } });
  fireEvent.change(screen.getByLabelText(/推論シード/), { target: { value: '12345' } });
  fireEvent.click(screen.getByLabelText(/評価中のGPU使用状況を計測/));
  fireEvent.click(screen.getByRole('button', { name: '新しいモデルを登録' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/models', expect.objectContaining({ backend: 'transformers', model: '/models/local', context_length: 2048, device: 'cuda', inference_seed: 12345, gpu_sampling: true })));
  expect(refresh).toHaveBeenCalled();
});


it('loads existing settings for editing and preserves non-form backend options', async () => {
  const model = { model_id: 'wrong', name: 'Wrong mock', backend: 'mock', model: 'wrong', endpoint: 'http://127.0.0.1:11434', revision: 'v1', quantization: 'N/A', temperature: 0.5, max_tokens: 2048, timeout_seconds: 60, mock_behavior: 'wrong', capabilities: { available: true, status: 'test-only', reason: 'fixture', native_tools: true } };
  render(<ModelManager models={[model as import('./types').Model]} refresh={vi.fn()} onError={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText('モデルID'), { target: { value: 'wrong' } });
  expect(screen.getByRole('button', { name: /登録済みIDです/ })).toBeDisabled();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  fireEvent.click(screen.getByRole('button', { name: '設定を編集' }));
  const editor = within(screen.getByRole('dialog'));
  expect(editor.getByLabelText('最大出力トークン')).toHaveValue(2048);
  fireEvent.change(editor.getByLabelText('表示名'), { target: { value: 'Renamed' } });
  fireEvent.click(screen.getByRole('button', { name: '「Wrong mock」の設定を更新' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/models', expect.objectContaining({ name: 'Renamed', mock_behavior: 'wrong', temperature: 0.5, max_tokens: 2048 })));
});
