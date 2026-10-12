import { expect, test } from '@playwright/test';

test('browser configuration → frozen set → run → logs → comparison', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'ベンチマークを、確かな比較へ。' })).toBeVisible();
  await page.getByRole('button', { name: '新しいベンチマーク', exact: true }).last().click();
  await expect(page.getByRole('heading', { name: '新しいベンチマーク', exact: true })).toBeVisible();
  await page.getByLabel('問題数', { exact: true }).fill('100');
  await expect(page.getByText('変更したカスタム')).toBeVisible();
  await page.getByRole('checkbox', { name: /Mock \/ 誤答テスト/ }).check();
  await page.getByRole('button', { name: '問題セットを確定する' }).click();
  await expect(page.getByRole('heading', { name: '確定した問題セット' })).toBeVisible();
  await expect(page.getByText('100問 · 固定50 / 動的50', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'このセットで実行する' }).click();
  await expect(page.getByRole('heading', { name: 'Mock / 参照ソルバー' })).toBeVisible();
  await page.getByRole('button', { name: '一時停止', exact: true }).click();
  await expect(page.getByRole('button', { name: '再開', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '再開', exact: true }).click();
  await expect(page.getByText('完了', { exact: true })).toBeVisible({ timeout: 20000 });
  await page.getByRole('tab', { name: '問題別ログ' }).click();
  await expect(page.locator('details.problem-log')).toHaveCount(100);
  await page.locator('details.problem-log').first().locator('summary').click();
  await expect(page.getByRole('heading', { name: '参照解答' }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Mock / 参照ソルバー' })).toBeVisible();
  await page.getByRole('button', { name: '実行履歴', exact: true }).click();
  await expect(page.getByText('Mock / 誤答テスト', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '結果を比較', exact: true }).click();
  await page.getByRole('checkbox', { name: /Mock \/ 参照ソルバー/ }).first().check();
  await page.getByRole('checkbox', { name: /Mock \/ 誤答テスト/ }).first().check();
  await page.getByRole('button', { name: '選択したランを比較' }).click();
  await expect(page.getByText('同一問題セット', { exact: true })).toBeVisible();
  await expect(page.getByText('Mock結果はソフトウェア診断です。正式なモデルランキングには含めません。')).toBeVisible();
});

test('mobile navigation and unsupported categories', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'メニューを開く' }).click();
  await page.getByRole('button', { name: '生成器・カバレッジ', exact: true }).click();
  await expect(page.getByRole('heading', { name: '生成器・カバレッジ', exact: true })).toBeVisible();
  await page.getByLabel('カテゴリ・生成器を検索').fill('コンピューター科学');
  await expect(page.getByText('検証済み生成器はまだありません。別分野への代替は行いません。')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});
