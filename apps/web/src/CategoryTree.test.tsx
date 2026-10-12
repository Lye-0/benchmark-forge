import { useState } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { CategoryTree } from './CategoryTree';
import type { Category } from './types';

afterEach(cleanup);
const categories: Category[] = [
  { id: '01', name: '数学', status: 'verified', subcategories: [{ id: '算術', name: '算術', generators: [
    { id: 'sum', name: '総和', category_id: '01', subcategory_id: '算術', status: 'verified', version: '1.0.0', template: 'sum', answer_type: 'number', difficulty_range: [0, 100] },
    { id: 'product', name: '積の計算', category_id: '01', subcategory_id: '算術', status: 'verified', version: '1.0.0', template: 'product', answer_type: 'number', difficulty_range: [0, 100] },
  ] }] },
  { id: '02', name: '論理', status: 'unavailable', subcategories: [] },
];
function Harness() {
  const [ids, setIds] = useState(['sum']);
  return <><CategoryTree categories={categories} selected={ids} onChange={setIds}/><output aria-label="選択ID">{ids.join(',')}</output></>;
}

describe('registry driven selection', () => {
  it('has three-level selection and parent indeterminate state', async () => {
    const user = userEvent.setup(); render(<Harness/>);
    expect((screen.getByLabelText('数学') as HTMLInputElement).indeterminate).toBe(true);
    await user.click(screen.getByLabelText('数学'));
    expect(screen.getByLabelText('選択ID')).toHaveTextContent('sum,product');
    expect(screen.getByLabelText('数学 / 算術')).toBeChecked();
    await user.click(screen.getByLabelText('数学 / 算術'));
    expect(screen.getByLabelText('選択ID')).toBeEmptyDOMElement();
    expect(screen.getByLabelText('論理')).toBeDisabled();
  });
  it('searches, collapses, selects all and clears without hard-coded generators', async () => {
    const user = userEvent.setup(); render(<Harness/>);
    await user.type(screen.getByLabelText('カテゴリ・生成器を検索'), '積の計算');
    expect(screen.getByText('積の計算')).toBeVisible();
    expect(screen.queryByText('総和')).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText('カテゴリ・生成器を検索'));
    await user.click(screen.getByText('折りたたむ'));
    expect(screen.queryByText('総和')).not.toBeInTheDocument();
    await user.click(screen.getByText('すべて展開'));
    expect(screen.getByText('総和')).toBeVisible();
    await user.click(screen.getByText('すべて選択'));
    expect(screen.getByLabelText('選択ID')).toHaveTextContent('sum,product');
    await user.click(screen.getByText('解除'));
    expect(screen.getByLabelText('選択ID')).toBeEmptyDOMElement();
  });
});
