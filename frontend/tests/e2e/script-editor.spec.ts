import { test, expect, request as apiRequest } from "@playwright/test";

// Mirrors the auth bootstrap in visual.spec.ts: the backend lives at BASE_URL,
// but pages are protected by a login screen, so we have to create an admin and
// sign in before exercising the script editor.

const BASE_URL = process.env.BASE_URL ?? "http://127.0.0.1:8765";
const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "hunter22pass";

test.beforeAll(async () => {
  const ctx = await apiRequest.newContext({ baseURL: BASE_URL });
  const res = await ctx.post("/api/kindling/auth/setup", {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  // 201 = first admin created. 404 = setup disabled because admin already
  // exists (e.g. re-run against same DB). Anything else is a real failure.
  expect([201, 404]).toContain(res.status());
});

test("quick-start -> edit -> save -> run", async ({ page }) => {
  // Auth: the editor lives behind /kindling which requires login.
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(ADMIN_EMAIL);
  await page.getByLabel(/password/i).fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard");

  // scripts.name is UNIQUE; re-running this spec against a persistent DB
  // would collide on the second run. Suffix with ms timestamp so each
  // invocation lands on a fresh row.
  const scriptName = `morning-report-${Date.now()}`;

  // Quick-start: pick the Python card on /kindling/scripts/new. The default
  // name is the "Untitled script" placeholder, which the new-script page now
  // blocks (mirrors the backend UNTITLED_PLACEHOLDER check); type a real name
  // first so the create call actually fires.
  await page.goto("/kindling/scripts/new");
  await page.getByTestId("new-name-input").fill(scriptName);
  await expect(page.getByTestId("quick-start-cards")).toBeVisible();
  await page.getByTestId("card-python").click();
  await page.waitForURL(/\/kindling\/scripts\/\d+/);

  // File tree should show seeded main.py + .env. Use role-based locators
  // so the entrypoint <select>'s <option value="main.py">main.py</option>
  // doesn't collide with the visible tree row (both contain the same
  // text and would violate strict mode).
  const tree = page.getByTestId("file-tree");
  await expect(tree).toBeVisible();
  await expect(tree.getByRole("button", { name: "main.py" })).toBeVisible();
  await expect(tree.getByRole("button", { name: ".env" })).toBeVisible();

  // Selecting main.py auto-loads the python template into the editor. Wait
  // for the debounce-save to settle (1500ms in EditorPanel + safety margin)
  // before triggering a run, so the runner sees the on-disk content.
  await tree.getByRole("button", { name: "main.py" }).click();
  await page.waitForTimeout(2000);

  // Run, then switch to Logs and wait for stdout from the python template.
  await page.getByRole("button", { name: /Run/i }).click();
  await page.getByRole("tab", { name: /Logs/i }).click();
  await expect(page.getByText(/Hello from Kindling/i)).toBeVisible({ timeout: 30000 });
});