import { defineConfig, devices } from "@playwright/test";

/** Run with scripts/e2e.sh, which starts the stub bot api and the standalone server first. */
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3123", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Desktop Chrome"], viewport: { width: 380, height: 780 }, isMobile: true, hasTouch: true } },
  ],
});
