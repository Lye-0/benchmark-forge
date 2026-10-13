import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { GroupScores } from './GroupScores';

afterEach(cleanup);
it('shows assigned denominators for partial runs and explains overlapping tags', () => {
  render(<GroupScores title="能力タグ別の成績" overlapping groups={{
    reasoning: { correct: 1, completed: 2, total: 4, accuracy: 0.25, weighted_contribution: 0.1 },
    arithmetic: { correct: 1, completed: 1, total: 4, accuracy: 0.25, weighted_contribution: 0.1 },
  }}/>);
  const row = screen.getByText('reasoning').closest('tr')!;
  expect(within(row).getByText('1 / 4')).toBeVisible();
  expect(within(row).getByText('2 / 4')).toBeVisible();
  expect(within(row).getByText('25.0%')).toBeVisible();
  expect(screen.getByText(/行同士を合計して総合点にはしません/)).toBeVisible();
});
