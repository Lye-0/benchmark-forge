import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from './api';
import { CalibrationAnalysis } from './CalibrationAnalysis';
afterEach(() => { cleanup(); vi.clearAllMocks(); });
vi.mock('./api', () => ({ api: vi.fn(), pct: (n: number) => `${n * 100}%` }));
const data = { model_count: 2, item_count: 1, category_count: 1, warnings: ['未校正の観測です'], by_difficulty: [{ lower: 0, upper: 10, items: 0, observations: 0, observed_accuracy: null }] };

it('shows missing observations as N/A and marks difficulty uncalibrated', async () => {
  vi.mocked(api).mockResolvedValue(data);
  render(<CalibrationAnalysis ids={['one', 'two']} onError={vi.fn()}/>);
  fireEvent.click(screen.getByRole('button'));
  expect(await screen.findByRole('status')).toHaveTextContent('難易度は未校正');
  expect(screen.getByText('N/A')).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith('/calibration-analysis?ids=one%2Ctwo');
});

it('discards the previous selection response and displays current errors', async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  const onError = vi.fn();
  const view = render(<CalibrationAnalysis ids={['old', 'two']} onError={onError}/>);
  fireEvent.click(screen.getByRole('button'));
  view.rerender(<CalibrationAnalysis ids={['new', 'two']} onError={onError}/>);
  await act(async () => resolve(data));
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  vi.mocked(api).mockRejectedValueOnce(new Error('同じモデルです'));
  fireEvent.click(screen.getByRole('button'));
  await waitFor(() => expect(onError).toHaveBeenCalledWith('同じモデルです'));
});
