import { test, expect, request as apiRequest } from "@playwright/test";

// Smoke-style smoke checks for the visual surface area: not full screenshot
// diffs (those require committed PNG baselines which drift with every UI
// tweak). These tests instead assert that key structural elements render.

const BASE_URL = process.env.BASE_URL ?? "http://127.0.0.1:8765";
const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "hunter22pass";

// Bootstrap the first admin via the public /auth/setup endpoint. CI starts
// the backend against a fresh DB on every run, so without this step the
// login submit below would 401 and time out. Setup is idempotent: once an
// admin exists the endpoint 404s, which we treat as already-bootstrapped.
test.beforeAll(async () => {
  const ctx = await apiRequest.newContext({ baseURL: BASE_URL });
  const res = await ctx.post("/api/kindling/auth/setup", {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  // 201 = first admin created. 404 = setup disabled because admin already
  // exists (e.g. re-run against same DB). Anything else is a real failure.
  expect([201, 404]).toContain(res.status());
});

async function ensureAuthed(page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(ADMIN_EMAIL);
  await page.getByLabel(/password/i).fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard");
}

test("login page renders", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByLabel(/email/i)).toBeVisible();
  await expect(page.getByLabel(/password/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
});

test("dashboard renders after login", async ({ page }) => {
  await ensureAuthed(page);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("dark mode toggle applies dark class", async ({ page }) => {
  await ensureAuthed(page);
  await page.getByRole("button", { name: /toggle theme/i }).click();
  await page.getByRole("menuitem", { name: /dark/i }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
});
