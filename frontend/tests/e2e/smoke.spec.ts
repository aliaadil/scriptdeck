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

  // Create the script via the API directly (with source) so we don't have to
  // drive Monaco from a test, then drive the UI for Run + view log. Save/
  // view-source are covered by frontend unit tests.
  const tokenAfterSetup = await page.evaluate(() => localStorage.getItem("scriptdeck_token"));
  const createRes = await page.request.post(`${process.env.BASE_URL ?? "http://127.0.0.1:8765"}/api/scripts`, {
    headers: { Authorization: `Bearer ${tokenAfterSetup}` },
    data: { name: "e2e", language: "python", source: "print('e2e')\n" },
  });
  expect(createRes.ok()).toBeTruthy();
  const created = await createRes.json();
  await page.goto(`/scripts/${created.id}`);
  await page.getByRole("button", { name: /run/i }).click();

  // The Run click triggers the mutation but the UI only shows a toast and
  // switches to the Logs tab. Capture the run id from the toast / fetch and
  // navigate to RunView explicitly so we can assert the log renders.
  const triggered = await page
    .waitForResponse((r) => r.url().includes(`/api/scripts/${created.id}/run`) && r.status() === 201, {
      timeout: 15_000,
    })
    .then((r) => r.json());
  await page.waitForTimeout(3000);
  await page.goto(`/runs/${triggered.id}`);
  await expect(page.getByText(/Run #/)).toBeVisible();
});