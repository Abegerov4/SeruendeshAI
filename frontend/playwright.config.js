import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser', timeout: 30000, workers: 1,
  use: {baseURL: 'http://127.0.0.1:5174', viewport: {width: 1440, height: 960},
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {},
    trace: 'retain-on-failure'},
  webServer: {command: 'npm run dev -- --host 127.0.0.1 --port 5174 --strictPort',
    url: 'http://127.0.0.1:5174', reuseExistingServer: false},
});
