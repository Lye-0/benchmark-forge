import { expect, test } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { ProgressWatch, waitForRuns, type RunProgress } from './run-progress';

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
  await page.getByRole('button', { name: '選択した2モデルの評価を開始' }).click();
  const { run_ids: runIds } = await (await started).json() as { run_ids: string[] };
  expect(runIds).toHaveLength(2);
  const batch = page.getByRole('region', { name: '今回開始したモデルの評価' });
  await expect(batch.getByText('Mock / 誤答テスト', { exact: true })).toBeVisible();
  await expect(batch.getByText('Mock / 参照ソルバー', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Mock / 参照ソルバー' })).toBeVisible();
  await page.getByRole('button', { name: 'このモデルを一時停止', exact: true }).click();
  await expect(page.getByRole('button', { name: 'このモデルを再開', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'このモデルを再開', exact: true }).click();
  const progress = new ProgressWatch(runIds, Date.now());
  await waitForRuns(progress, async () => {
    const response = await request.get('/api/runs', { timeout: 5000 });
    try {
      expect(response.ok()).toBeTruthy();
      return await response.json() as RunProgress[];
    } finally { await response.dispose(); }
  });
  // Backend completion must still reach the UI promptly, without a reload.
  await expect(page.locator('.page-heading').getByText('完了', { exact: true })).toBeVisible({ timeout: 5000 });
  await page.getByRole('tab', { name: '問題別ログ' }).click();
  await expect(page.locator('details.problem-log')).toHaveCount(50);
  await expect(page.getByText('1–50 / 100件', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '次の50件' }).click();
  await expect(page.getByText('51–100 / 100件', { exact: true })).toBeVisible();
  await expect(page.locator('details.problem-log')).toHaveCount(50);
  await page.locator('details.problem-log').first().locator('summary').first().click();
  await expect(page.getByRole('heading', { name: '参照解答' }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Mock / 参照ソルバー' })).toBeVisible();
  await expect(batch).toBeVisible();
  await batch.getByRole('button', { name: 'Mock / 誤答テストの詳細' }).click();
  await expect(page.getByRole('heading', { name: 'Mock / 誤答テスト' })).toBeVisible();
  await page.reload();
  await expect(batch.getByText('Mock / 参照ソルバー', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Mock / 誤答テスト' })).toBeVisible();
  await page.getByRole('button', { name: '実行履歴', exact: true }).click();
  await expect(page.getByText('Mock / 誤答テスト', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '結果を比較', exact: true }).click();
  await page.getByRole('checkbox', { name: /Mock \/ 参照ソルバー/ }).first().check();
  await page.getByRole('checkbox', { name: /Mock \/ 誤答テスト/ }).first().check();
  await page.getByRole('button', { name: '選択した実行を比較' }).click();
  await expect(page.getByText('同一問題セット', { exact: true })).toBeVisible();
  await expect(page.getByText('Mock結果はソフトウェア診断です。正式なモデルランキングには含めません。')).toBeVisible();
  await page.getByRole('button', { name: '選択したランの観測を集計' }).click();
  await expect(page.getByText('校正用データには完了した実モデルの能力評価ランが必要です')).toBeVisible();
  await page.getByLabel('元の実行', { exact: true }).selectOption(runIds[0]);
  await page.getByLabel('追加評価モデル', { exact: true }).selectOption('mock-wrong');
  const reused = page.waitForResponse(r => r.url().endsWith('/api/runs') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '保存済みセットで実行', exact: true }).click();
  const { run_ids: reusedIds } = await (await reused).json() as { run_ids: string[] };
  expect(reusedIds).toHaveLength(1);
  expect(reusedIds[0]).not.toBe(runIds[0]);
  const originalRun = await (await request.get(`/api/runs/${runIds[0]}?detail=false`)).json();
  const extraRun = await (await request.get(`/api/runs/${reusedIds[0]}?detail=false`)).json();
  expect(extraRun.set_hash).toBe(originalRun.set_hash);
  expect(extraRun.model.model_id).toBe('mock-wrong');
  expect(originalRun.correct).toBe(100);
});

test('mobile navigation and unsupported categories', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#unknown');
  await expect(page.getByRole('heading', { name: 'ベンチマークを、確かな比較へ。' })).toBeVisible();
  await expect(page.locator('#navigation')).toHaveAttribute('inert', '');
  await page.getByRole('button', { name: 'メニューを開く' }).click();
  await expect(page.locator('#navigation button').first()).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'メニューを開く' })).toBeFocused();
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
  await expect(page.getByText(/1問を取り込み済み/)).toBeVisible();
  const holdout = page.locator('section').filter({ has: page.getByRole('heading', { name: '私有holdoutの取り込み' }) });
  await holdout.getByRole('checkbox', { name: 'Mock / 参照ソルバー' }).check();
  await holdout.getByRole('checkbox', { name: 'Mock / 誤答テスト' }).check();
  await holdout.getByRole('button', { name: '選択した2モデルで取り込み済みの問題を評価' }).click();
  await expect(page.getByRole('region', { name: '今回開始したモデルの評価' })).toBeVisible();
  await page.getByRole('button', { name: 'プロファイル・設定', exact: true }).click();
  await page.getByLabel('独立評価モード').selectOption('agent');
  await page.getByRole('button', { name: '独立評価を開始（5問）' }).click();
  await expect(page.getByText('完了', { exact: true }).first()).toBeVisible({ timeout: 10000 });
  await page.getByRole('tab', { name: '問題別ログ' }).click();
  await expect(page.locator('details.problem-log')).toHaveCount(5);
});

test('speed probe is labeled separately from ability', async ({ page }) => {
  await page.goto('/#settings');
  await page.getByRole('button', { name: '速度試験を開始（3回）' }).click();
  await expect(page.getByText(/専用速度試験：正答率は出力形式の遵守確認/)).toBeVisible();
  await expect(page.getByText('完了', { exact: true }).first()).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`model buttons and popup editing at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/#models');
    const card = page.locator('.model-card').filter({ has: page.getByRole('heading', { name: 'Mock / 誤答テスト', exact: true }) });
    const edit = card.getByRole('button', { name: '設定を編集' });
    const check = card.getByRole('button', { name: '対応機能を確認' });
    const a = await edit.boundingBox(); const b = await check.boundingBox();
    expect(a && b && (b.x >= a.x + a.width + 8 || b.y >= a.y + a.height + 8)).toBeTruthy();
    await page.getByLabel('表示名', { exact: true }).fill('未保存の新規モデル');
    await edit.click();
    const dialog = page.getByRole('dialog', { name: 'モデル設定を編集' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('表示名', { exact: true })).toHaveValue('Mock / 誤答テスト');
    await dialog.getByLabel('表示名', { exact: true }).fill('保存しない編集');
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(edit).toBeFocused();
    await expect(page.getByLabel('表示名', { exact: true })).toHaveValue('未保存の新規モデル');
    await edit.click();
    await expect(dialog.getByLabel('表示名', { exact: true })).toHaveValue('Mock / 誤答テスト');
    await dialog.getByLabel('温度', { exact: true }).fill('0.2');
    await dialog.getByRole('button', { name: '「Mock / 誤答テスト」の設定を更新' }).click();
    await expect(dialog).not.toBeVisible();
    await expect(card.getByText('0.2 / 512 tokens')).toBeVisible();
    await edit.click();
    await expect(dialog.getByLabel('温度', { exact: true })).toHaveValue('0.2');
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.screenshot({ path: `/tmp/model-editor-${width}.png` });
    await dialog.getByRole('button', { name: 'キャンセル', exact: true }).click();
    await expect(dialog).not.toBeVisible();
  });
}

test('deletion confirms each target and preserves history after model removal', async ({ page, request }) => {
  const model = { model_id: 'delete-fixture', name: '削除確認用モデル', backend: 'mock' };
  expect((await request.post('/api/models', { data: model })).ok()).toBe(true);
  const frozen = await (await request.post('/api/sets', { data: { generator_ids: ['math.linear'], count: 1, fixed_ratio: 0, seed: 42 } })).json();
  const { run_ids: [id] } = await (await request.post('/api/runs', { data: { set_id: frozen.set_id, model_ids: [model.model_id] } })).json();
  await expect.poll(async () => (await (await request.get(`/api/runs/${id}`)).json()).status).toBe('completed');
  await page.goto('/#models');
  const card = page.locator('.model-card').filter({ hasText: model.name });
  await card.getByRole('button', { name: '削除', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('モデル本体のファイル');
  await dialog.getByRole('button', { name: 'キャンセル' }).click();
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: '削除', exact: true }).click();
  await dialog.getByRole('button', { name: '削除する', exact: true }).click();
  await expect(card).toHaveCount(0);
  expect((await request.get(`/api/runs/${id}`)).ok()).toBe(true);
  await page.getByRole('button', { name: '実行履歴', exact: true }).click();
  const row = page.getByRole('row').filter({ hasText: model.name });
  await row.getByRole('button', { name: '削除', exact: true }).click();
  await expect(dialog).toContainText(id);
  await dialog.getByRole('button', { name: '削除する', exact: true }).click();
  await expect(row).toHaveCount(0);
  expect((await request.get(`/api/runs/${id}`)).status()).toBe(404);
  expect((await request.get(`/api/sets/${frozen.set_id}`)).ok()).toBe(true);
});

test('installed Ollama choices fill registration without saving or overwriting user labels', async ({ page }) => {
  await page.route('**/api/ollama/models', route => route.fulfill({ json: { models: [
    { name: 'qwen3:0.6b', revision: 'a'.repeat(64), quantization: 'Q4_K_M', size_bytes: 500000000 },
    { name: 'gemma:test', revision: 'b'.repeat(64), quantization: 'Q8_0', size_bytes: 1000000000 },
  ] } }));
  await page.goto('/#models');
  const choice = page.getByLabel('インストール済みモデルから入力');
  await expect(choice).toBeEnabled();
  await choice.selectOption('qwen3:0.6b');
  await expect(page.getByLabel('Ollamaのモデル名（タグを含む）')).toHaveValue('qwen3:0.6b');
  await expect(page.getByLabel('モデルID', { exact: true })).toHaveValue('ollama-qwen3-0.6b');
  await expect(page.getByLabel('表示名', { exact: true })).toHaveValue('qwen3:0.6b');
  await expect(page.getByLabel('リビジョン', { exact: true })).toHaveValue('a'.repeat(64));
  await page.getByLabel('表示名', { exact: true }).fill('自分の表示名');
  await choice.selectOption('gemma:test');
  await expect(page.getByLabel('モデルID', { exact: true })).toHaveValue('ollama-gemma-test');
  await expect(page.getByLabel('表示名', { exact: true })).toHaveValue('自分の表示名');
  await expect(page.getByLabel('量子化', { exact: true })).toHaveValue('Q8_0');
  await page.unroute('**/api/ollama/models');
  await page.route('**/api/ollama/models', route => route.fulfill({ status: 503, json: { detail: 'Ollamaを起動してください' } }));
  await page.getByRole('button', { name: '候補を再取得' }).click();
  await expect(page.getByText('Ollamaを起動してください')).toBeVisible();
  await expect(page.getByLabel('Ollamaのモデル名（タグを含む）')).toBeEnabled();
});
