import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { GpuMeasurements } from './GpuMeasurements';

afterEach(cleanup);
it('preserves measured zero and missing counters without calling device totals a model peak', () => {
  render(<GpuMeasurements value={{ scope: 'ホスト全体・モデル専用ではありません', samples: 2, failed_samples: 1, devices: [{ uuid: 'fixture', name: 'GPU fixture', metrics: { utilization_percent: { samples: 2, mean: 0, observed_max: 0 }, power_watts: { samples: 0, mean: null, observed_max: null } } }] }}/>);
  expect(screen.getAllByText('0.0 %')).toHaveLength(2);
  expect(screen.getAllByText('N/A')).toHaveLength(6);
  expect(screen.getByText('観測最大値')).toBeVisible();
  expect(screen.getByText('ホスト全体・モデル専用ではありません')).toBeVisible();
});
