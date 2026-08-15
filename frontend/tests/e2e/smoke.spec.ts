import { test, expect } from "@playwright/test";

// NOTE: brief assumes hitting /dashboard on a fresh DB redirects to /setup.
// Actual ProtectedRoute redirects any unauthenticated request to /login.
// We navigate to /setup directly, which is the only path that exposes the
// first-admin form when users are empty.
test("setup → create script → trigger run → view log", async ({ page }) => {
  await page.goto("/setup");

  await page.fill('input[type="email"]', "admin@test.local");
  await page.fill('input[type="password"]', "hunter22pass");
  await page.click('button[type="submit"]');

  await page.waitForURL("**/dashboard");
  await expect(page.getByText("Dashboard")).toBeVisible();

  await page.goto("/scripts");
  await page.getByRole("button", { name: "New script" }).click();
  await page.fill('input[required]', "e2e");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/scripts\/\d+/);

  // Trigger a run manually via API.
  const token = await page.evaluate(() => localStorage.getItem("scriptdeck_token"));
  const scriptId = Number(page.url().split("/").pop());
  const runRes = await page.request.post(`${process.env.BASE_URL ?? "http://127.0.0.1:8765"}/api/runs`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { script_id: scriptId },
  });
  expect(runRes.ok()).toBeTruthy();
  const run = await runRes.json();

  await page.waitForTimeout(3000);
  await page.goto(`/runs/${run.id}`);
  await expect(page.getByText(/Run #/)).toBeVisible();
});
