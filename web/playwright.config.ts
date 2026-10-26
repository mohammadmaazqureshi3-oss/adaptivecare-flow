// Browser tests of the web app (plan Section 14: system and scenario tests with Playwright).
// They need the running platform: ./scripts/dev.sh and scripts/seed_demo.py, then
// `npm run dev` here (or E2E_BASE_URL=https://localhost:8443 for Compose). Run: npm run e2e.
// The installed Google Chrome is used (no browser download); E2E_CHANNEL=chromium after
// `npx playwright install chromium` uses Playwright's own.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts",
  timeout: 120_000,
  workers: 1, // one shared platform: tests run one after another
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    channel: process.env.E2E_CHANNEL ?? "chrome",
    headless: true,
    ignoreHTTPSErrors: true, // the Compose stack's self-signed certificate
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
