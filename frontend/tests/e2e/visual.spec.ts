import { test, expect } from "@playwright/test";

// Visual snapshot spec.
//
// Baseline PNGs are generated on first run (--update-snapshots) and stored under
// frontend/tests/e2e/visual.spec.ts-snapshots/. Re-running without that flag
// will compare screenshots and fail on drift. CI test only runs when explicitly
// invoked; designers can refresh baselines locally after intentional UI changes.

test("login page renders", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveScreenshot("login.png", { fullPage: true });
});

test("dashboard renders after login", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("admin@example.com");
  await page.getByLabel(/password/i).fill("password123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard");
  await expect(page).toHaveScreenshot("dashboard.png", { fullPage: true });
});

test("dark mode toggle applies dark class", async ({ page }) => {
  await page.goto("/login");
  // ModeToggle trigger: <Button aria-label="Toggle theme">.
  await page.getByRole("button", { name: /toggle theme/i }).click();
  // DropdownMenuItem renders role="menuitem"; "Dark" matches /dark/i.
  await page.getByRole("menuitem", { name: /dark/i }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
});
