import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ModelManager } from './ModelManager';
import { api } from './api';

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
