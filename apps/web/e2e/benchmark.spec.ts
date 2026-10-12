import { expect, test } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { ProgressWatch, type RunProgress } from './run-progress';

// Capture durable state separately from the DOM, and prevent a failed test's queued
// runs from delaying unrelated tests. This server/DB is exclusive to this suite.
test.afterEach(async ({ request }, testInfo) => {
  const response = await request.get('/api/runs');
  expect(response.ok()).toBeTruthy();
  const runs = await response.json() as { id: string; status: string; completed: number; total: number; revision: number }[];
  if (testInfo.status !== testInfo.expectedStatus) {
    const summary = JSON.stringify(runs.map(({ id, status, completed, total, revision }) => ({ id, status, completed, total, revision })), null, 2);
    console.log('durable-run-progress:', summary);
    const path = testInfo.outputPath('durable-run-progress.json');
    await writeFile(path, summary, 'utf8');
    await testInfo.attach('durable-run-progress', { contentType: 'application/json', path });
  }
  for (const run of runs) {
    if (['queued', 'running', 'pausing', 'paused'].includes(run.status)) {
      const cancelled = await request.post(`/api/runs/${run.id}/cancel`, { data: {} });
      // It may complete between reading the snapshot and cancelling it.
      if (!cancelled.ok()) {
        const latest = await request.get(`/api/runs/${run.id}`);
        expect(['completed', 'cancelled']).toContain((await latest.json()).status);
      }
    }
  }
});

test('browser configuration → frozen set → run → logs → comparison', async ({ page, request }) => {
  test.setTimeout(150000); // Up to 200 durable problem writes, then a separate UI deadline.
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
  const started = page.waitForResponse(r => r.url().endsWith('/api/runs') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'このセットで実行する' }).click();
  const { run_ids: runIds } = await (await started).json() as { run_ids: string[] };
  expect(runIds).toHaveLength(2);
  await expect(page.getByRole('heading', { name: 'Mock / 参照ソルバー' })).toBeVisible();
  await page.getByRole('button', { name: '一時停止', exact: true }).click();
  await expect(page.getByRole('button', { name: '再開', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '再開', exact: true }).click();
  const progress = new ProgressWatch(runIds, Date.now());
  for (;;) {
    const response = await request.get('/api/runs', { timeout: 5000 });
    expect(response.ok()).toBeTruthy();
    const rows = await response.json() as RunProgress[];
    if (progress.observe(rows, Date.now())) break;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  // Backend completion must still reach the UI promptly, without a reload.
  await expect(page.getByText('完了', { exact: true })).toBeVisible({ timeout: 5000 });
  await page.getByRole('tab', { name: '問題別ログ' }).click();
  await expect(page.locator('details.problem-log')).toHaveCount(100);
  await page.locator('details.problem-log').first().locator('summary').first().click();
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
  await page.getByLabel('カテゴリ・生成器を検索').fill('一般知識・専門知識');
  await expect(page.getByText('検証済み生成器はまだありません。別分野への代替は行いません。')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});

test('private holdout import and independent native tool evaluation', async ({ page }) => {
  await page.goto('/#settings');
  const jsonl = [
    { schema: 'forge-holdout-v1', name: 'E2E private fixture', source: 'original', license: 'private-use' },
    { prompt: 'Private fixture: output ok', category_id: '07', target_difficulty: 10, answer_spec: { type: 'text', expected: 'ok' } },
  ].map(x => JSON.stringify(x)).join('\n');
  await page.getByLabel('私有問題JSONL').setInputFiles({ name: 'fixture.jsonl', mimeType: 'application/x-ndjson', buffer: Buffer.from(jsonl) });
  await expect(page.getByText('1問を取り込みました。')).toBeVisible();
  await page.getByLabel('独立評価モード').selectOption('agent');
  await page.getByRole('button', { name: '独立評価を開始（5問）' }).click();
  await expect(page.getByText('完了', { exact: true }).first()).toBeVisible({ timeout: 10000 });
  await page.getByRole('tab', { name: '問題別ログ' }).click();
  await expect(page.locator('details.problem-log')).toHaveCount(5);
});

test('speed probe is labeled separately from ability', async ({ page }) => {
  await page.goto('/#settings');
  await page.getByRole('button', { name: '速度試験を開始' }).click();
  await expect(page.getByText(/専用速度試験：正答率は出力形式の遵守確認/)).toBeVisible();
  await expect(page.getByText('完了', { exact: true }).first()).toBeVisible();
});
