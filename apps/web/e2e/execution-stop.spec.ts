import { test, expect } from '@playwright/test';
import { createServer } from 'node:http';
import { ProgressWatch, waitForRuns, type RunProgress } from './run-progress';
import type { AddressInfo } from 'node:net';

test('Ollama outage stops without scoring, survives reload and resumes the failed question', async ({ page, request }, testInfo) => {
  test.setTimeout(120000);
  let online = true;
  let chats = 0;
  let runId: string | undefined;
  const prompts: string[] = [];
  const server = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    res.setHeader('Content-Type', 'application/json');
    if (!online) { res.writeHead(503); res.end('{"error":"offline"}'); return; }
    if (req.url === '/api/tags') res.end(JSON.stringify({ models: [{ name: 'fixture:latest' }] }));
    else if (req.url === '/api/show') res.end('{}');
    else {
      chats += 1;
      // A real answer may take longer than the UI's five-second notification budget.
      if (chats === 1) await new Promise(resolve => setTimeout(resolve, 6000));
      prompts.push(JSON.parse(body).messages[0].content);
      if (chats === 2) { online = false; res.writeHead(500); res.end('{"error":"model failed to load"}'); }
      else res.end(JSON.stringify({ message: { content: '0' }, done: true }));
    }
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const endpoint = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try {
    expect((await request.post('/api/models', { data: { model_id: 'outage-fixture', name: '接続断テスト', model: 'fixture', backend: 'ollama', endpoint } })).ok()).toBe(true);
    const frozen = await (await request.post('/api/sets', { data: { generator_ids: ['math.linear'], count: 2, fixed_ratio: 0, seed: 77 } })).json();
    online = false;
    await page.goto('/#new');
    await page.getByRole('checkbox', { name: /Mock \/ 参照ソルバー/ }).uncheck();
    await page.getByRole('checkbox', { name: /接続断テスト/ }).check();
    await page.getByRole('button', { name: '問題セットを確定する' }).click();
    await page.getByRole('button', { name: '選択した1モデルの評価を開始' }).click();
    const refused = page.getByRole('dialog', { name: '評価を開始できません' });
    await expect(refused).toContainText('Ollamaに接続できません');
    expect(chats).toBe(0);
    await refused.getByRole('button', { name: '閉じる' }).click();
    online = true;
    await page.getByRole('button', { name: '実行履歴', exact: true }).click();
    const started = await request.post('/api/runs', { data: { set_id: frozen.set_id, model_ids: ['outage-fixture'] } });
    expect(started.ok()).toBe(true);
    const { run_ids: [id] } = await started.json();
    runId = id;
    const readProgress = async () => {
      const response = await request.get(`/api/runs/${id}?detail=false`, { timeout: 5000 });
      try { expect(response.ok()).toBe(true); return [await response.json() as RunProgress]; }
      finally { await response.dispose(); }
    };
    // First require the durable stop; only then measure notification latency.
    await waitForRuns(new ProgressWatch([id], Date.now(), 15000, 30000, 'paused'), readProgress);
    const dialog = page.getByRole('dialog', { name: 'モデルの評価を自動停止しました' });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('接続断テスト');
    const paused = await (await request.get(`/api/runs/${id}`)).json();
    expect(paused.status).toBe('paused');
    expect(paused.completed).toBe(1);
    expect(paused.status_counts.error).toBeUndefined();
    expect(chats).toBe(2);
    await dialog.getByRole('button', { name: '閉じる' }).click();
    await expect(dialog).not.toBeVisible();
    await page.goto(`/#run/${id}`);
    await expect(page.getByRole('alert')).toContainText('実行不能のため自動停止');
    await page.reload();
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: '接続を確認して再開' }).click();
    await expect(dialog.getByRole('alert')).toContainText('Ollamaに接続できません');
    expect((await (await request.get(`/api/runs/${id}`)).json()).status).toBe('paused');
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('execution-stop-dialog.png') });
    online = true;
    await dialog.getByRole('button', { name: '接続を確認して再開' }).click();
    await expect(dialog).not.toBeVisible();
    await waitForRuns(new ProgressWatch([id], Date.now(), 15000, 30000), readProgress);
    expect(chats).toBe(3);
    expect(prompts[1]).toBe(prompts[2]);
  } finally {
    if (runId) {
      const saved = await (await request.get(`/api/runs/${runId}`)).json();
      if (testInfo.status !== testInfo.expectedStatus) {
        const { id, status, completed, total, revision, execution_block } = saved;
        const detail = JSON.stringify({ id, status, completed, total, revision, execution_block, fixture_chats: chats, fixture_online: online }, null, 2);
        console.log('durable-execution-stop:', detail);
        await testInfo.attach('durable-execution-stop', { body: detail, contentType: 'application/json' });
      }
      if (['queued', 'running', 'pausing', 'paused'].includes(saved.status)) await request.post(`/api/runs/${runId}/cancel`, { data: {} });
    }
    await request.post('/api/models/outage-fixture/delete', { data: {} });
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
});
