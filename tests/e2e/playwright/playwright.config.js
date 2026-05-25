// @ts-check
const { defineConfig, devices } = require('@playwright/test');
const path = require('path');

const ARTIFACT_DIR = path.resolve(__dirname, '..', '..', '..', '.walletsavior-live-validation', 'ui-e2e');

module.exports = defineConfig({
  testDir: './specs',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(ARTIFACT_DIR, 'report.json') }],
    ['html', { outputFolder: path.join(ARTIFACT_DIR, 'html'), open: 'never' }],
  ],
  outputDir: path.join(ARTIFACT_DIR, 'test-output'),
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 8_000,
    navigationTimeout: 20_000,
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 900 } },
      testIgnore: /mobile\.spec\.js$/,
    },
    {
      name: 'mobile-480',
      use: { ...devices['Desktop Chrome'], viewport: { width: 480, height: 800 }, isMobile: false, hasTouch: true },
      testMatch: /mobile\.spec\.js$/,
    },
    {
      name: 'tablet-768',
      use: { ...devices['Desktop Chrome'], viewport: { width: 768, height: 1024 }, isMobile: false, hasTouch: true },
      testMatch: /mobile\.spec\.js$/,
    },
  ],
});

module.exports.ARTIFACT_DIR = ARTIFACT_DIR;
