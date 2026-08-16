import { test, expect } from "@playwright/test";

// NOTE: brief assumes hitting /dashboard on a fresh DB redirects to /setup.
// Actual ProtectedRoute redirects any unauthenticated request to /login.
// We navigate to /setup directly, which is the only path that exposes the
// first-admin form when users are empty.
test("setup → create script → trigger run → view log", async ({ page }) => {
  await page.goto("/setup");

  // shadcn Field + Input: label uses htmlFor; getByLabel matches by accessible name.
  await page.getByLabel(/email/i).fill("admin@example.com");
  await page.getByLabel(/password/i).fill("hunter22pass");
  // SetupPage submit button text is "Create admin".
  await page.getByRole("button", { name: /create admin/i }).click();

  await page.waitForURL("**/dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await page.goto("/scripts");
  // Scripts page exposes a <Button>New script</Button> per task 11.
  await page.getByRole("button", { name: /new script/i }).click();

  // ScriptEdit also has an inline name input in the header, so target the
  // Config tab's input by id to avoid the strict-mode ambiguity.
  await page.getByRole("tab", { name: /config/i }).click();
  await page.locator("#name").fill("e2e");
  await page.getByRole("button", { name: /^save$/i }).click();
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
  // RunView shows "Run #{id}" in heading per task 15.
  await expect(page.getByText(/Run #/)).toBeVisible();
});
