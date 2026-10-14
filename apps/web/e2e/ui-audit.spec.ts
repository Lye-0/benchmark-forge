import { test, expect } from '@playwright/test';

for (const width of [1440, 390]) {
  test(`all UI routes and panels at ${width}px`, async ({ page, request }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width, height: 1000 });
    await page.route('**/api/ollama/models', route => route.fulfill({ json: { models: [{ name: 'qwen3:0.6b', quantization: 'Q4_K_M', revision: 'a'.repeat(64), size_bytes: 500000000 }] } }));
    const frozen = await (await request.post('/api/sets', { data: { generator_ids: ['math.linear'], count: 2, seed: 67, fixed_ratio: 0 } })).json();
    const { run_ids: ids } = await (await request.post('/api/runs', { data: { set_id: frozen.set_id, model_ids: ['mock-reference', 'mock-wrong'] } })).json();
    await expect.poll(async () => (await (await request.get(`/api/runs/${ids[1]}`)).json()).status).toBe('completed');
    for (const route of ['dashboard', 'new', 'history', 'compare', 'models', 'generators', 'settings', `run/${ids[0]}?batch=${ids.join(',')}`]) {
      const key = route.startsWith('run/') ? 'run' : route;
      await page.goto('/#' + route);
      await expect(page.locator('main h1')).toBeVisible();
      if (key === 'new' || key === 'generators') await page.getByRole('button', { name: '折りたたむ', exact: true }).click();
      if (key === 'compare') {
        await page.getByRole('checkbox').nth(0).check();
        await page.getByRole('checkbox').nth(1).check();
        await page.getByRole('button', { name: '選択した実行を比較' }).click();
        await expect(page.getByRole('heading', { name: '比較結果' })).toBeVisible();
      }
      await page.screenshot({ path: `/tmp/ui-audit-${width}-${key}.png`, fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (overflow) console.log(key, await page.locator('body *').evaluateAll(nodes => nodes.map(el => ({ tag: el.tagName, cls: el.className, right: el.getBoundingClientRect().right, width: el.getBoundingClientRect().width })).filter(x => x.right > innerWidth + 1).slice(0, 15)));
      expect(overflow, `${key} page overflow`).toBe(false);
      if (key === 'settings') {
        await page.getByRole('heading', { name: '実行環境・データ' }).scrollIntoViewIfNeeded();
        const torch = await page.getByRole('button', { name: 'PyTorch / CUDAを確認' }).boundingBox();
        const gpu = await page.getByRole('button', { name: 'GPUの現在値を確認' }).boundingBox();
        expect(torch && gpu && gpu.y >= torch.y + torch.height + 8).toBeTruthy();
        await page.screenshot({ path: `/tmp/ui-audit-${width}-diagnostics.png` });
      }
      if (key === 'history') {
        await page.getByRole('button', { name: '削除', exact: true }).first().click();
        const dialog = page.getByRole('dialog');
        await expect(dialog).toBeVisible();
        expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
        await page.screenshot({ path: `/tmp/ui-audit-${width}-delete.png` });
        await page.keyboard.press('Escape');
      }
      if (key === 'run') {
        await page.getByText('区間ごとのサンプル数・不確実性', { exact: true }).click();
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
        await page.getByRole('tab', { name: '問題別ログ' }).click();
        await expect(page.locator('.problem-log')).toHaveCount(2);
        await page.locator('.problem-log summary').first().click();
        await page.screenshot({ path: `/tmp/ui-audit-${width}-logs.png`, fullPage: true });
        await page.getByRole('tab', { name: '実行条件' }).click();
        await page.screenshot({ path: `/tmp/ui-audit-${width}-config.png` });
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      }
    }
  });
}

test('navigation scrolls on a short landscape screen', async ({ page }) => {
  await page.setViewportSize({ width: 740, height: 360 });
  await page.goto('/');
  await page.getByRole('button', { name: 'メニューを開く' }).click();
  await page.getByRole('button', { name: 'プロファイル・設定', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'プロファイル・設定', exact: true })).toBeVisible();
});
