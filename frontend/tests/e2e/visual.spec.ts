import { test, expect } from "@playwright/test";

// Smoke-style smoke checks for the visual surface area: not full screenshot
// diffs (those require committed PNG baselines which drift with every UI
// tweak). These tests instead assert that key structural elements render.

async function ensureAuthed(page) {
  await page.goto("/login");
  if (page.url().endsWith("/setup")) {
    await page.getByLabel(/email/i).fill("admin@example.com");
    await page.getByLabel(/password/i).fill("hunter22pass");
    await page.getByRole("button", { name: /create admin/i }).click();
  } else if ((await page.getByLabel(/password/i).count()) > 0) {
    await page.getByLabel(/email/i).fill("admin@example.com");
    await page.getByLabel(/password/i).fill("hunter22pass");
    await page.getByRole("button", { name: /sign in/i }).click();
  }
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
