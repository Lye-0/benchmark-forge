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
  fireEvent.change(screen.getByLabelText('モデル名 / ローカル識別子'), { target: { value: '/models/local' } });
  fireEvent.change(screen.getByLabelText(/コンテキスト上限/), { target: { value: '2048' } });
  fireEvent.change(screen.getByLabelText(/推論デバイス/), { target: { value: 'cuda' } });
  fireEvent.click(screen.getByRole('button', { name: 'モデルを保存' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/models', expect.objectContaining({ backend: 'transformers', model: '/models/local', context_length: 2048, device: 'cuda' })));
  expect(refresh).toHaveBeenCalled();
});
