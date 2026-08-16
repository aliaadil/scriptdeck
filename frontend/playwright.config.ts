import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:8765",
    trace: "retain-on-failure",
  },
  webServer: process.env.CI
    ? undefined
    : {
        command: "uv run python -m scriptdeck serve",
        url: "http://127.0.0.1:8765/api/health",
        reuseExistingServer: true,
        timeout: 60_000,
      },
  projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
});
