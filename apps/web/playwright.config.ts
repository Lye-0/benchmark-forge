import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const testData = mkdtempSync(join(tmpdir(), 'benchmark-forge-e2e-'));
export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:5187', browserName: 'chromium', trace: 'retain-on-failure', launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } },
  webServer: [
    { command: process.platform === 'win32' ? 'powershell -NoProfile -File ../../scripts/start.ps1 -Port 8017' : 'uv run --no-sync --project ../.. forge serve --port 8017', env: { UV_CACHE_DIR: process.env.UV_CACHE_DIR || join(tmpdir(), 'benchmark-forge-uv'), FORGE_DATA_DIR: testData, FORGE_WEB_ORIGIN: 'http://127.0.0.1:5187' }, url: 'http://127.0.0.1:8017/api/health', reuseExistingServer: false },
    { command: 'npm run dev', env: { FORGE_WEB_PORT: '5187', FORGE_API_PORT: '8017' }, url: 'http://127.0.0.1:5187', reuseExistingServer: false },
  ],
});
