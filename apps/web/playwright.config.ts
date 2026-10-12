import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const testData = mkdtempSync(join(tmpdir(), 'benchmark-forge-e2e-'));
export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:5187', browserName: 'chromium', trace: 'retain-on-failure', launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } },
  webServer: [
    { command: `FORGE_DATA_DIR=${testData} FORGE_WEB_ORIGIN=http://127.0.0.1:5187 UV_CACHE_DIR=/tmp/benchmark-forge-uv uv run --project ../.. forge serve --port 8017`, url: 'http://127.0.0.1:8017/api/health', reuseExistingServer: false },
    { command: 'FORGE_WEB_PORT=5187 FORGE_API_PORT=8017 npm run dev', url: 'http://127.0.0.1:5187', reuseExistingServer: false },
  ],
});
