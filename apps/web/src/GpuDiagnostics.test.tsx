import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GpuDiagnostics } from './GpuDiagnostics';
import { api } from './api';

vi.mock('./api', () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it('measures only on request and keeps unsupported counters distinct from zero', async () => {
  vi.mocked(api).mockResolvedValue({ available: true, reason: null, scope: 'GPU全体の単発計測', observed_at: '2026-10-13T00:00:00Z', devices: [{
    uuid: 'fixture', name: 'Fixture GPU', utilization_percent: 0, used_vram_bytes: 1048576,
    power_watts: null, temperature_celsius: 40, unavailable_reasons: { power_watts: 'unsupported' },
  }] });
  render(<GpuDiagnostics/>);
  expect(api).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'GPUの現在値を確認' }));
  expect(await screen.findByText('Fixture GPU')).toBeVisible();
  expect(screen.getByText('0.0 %')).toBeVisible();
  expect(screen.getByText('N/A')).toBeVisible();
  expect(api).toHaveBeenCalledWith('/environment/gpu', {});
});
it('shows absence of nvidia-smi without claiming measurements', async () => {
  vi.mocked(api).mockResolvedValue({ available: false, devices: null, observed_at: null, reason: 'nvidia-smiがありません', scope: 'GPU全体の単発計測' });
  render(<GpuDiagnostics/>);
  fireEvent.click(screen.getByRole('button', { name: 'GPUの現在値を確認' }));
  expect(await screen.findByText('nvidia-smiがありません')).toBeVisible();
  expect(screen.queryByText('GPU使用率')).not.toBeInTheDocument();
});
