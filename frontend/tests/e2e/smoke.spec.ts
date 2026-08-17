import { test, expect } from '@playwright/test';

test('dashboard mounts at /kindling/', async ({ page }) => {
  await page.goto('/kindling/');
  await expect(page).toHaveTitle(/Kindling/);
  await expect(page.getByAltText('Kindling')).toBeVisible();
});

test('logo asset served', async ({ page }) => {
  const res = await page.goto('/kindling/logo.svg');
  expect(res?.status()).toBe(200);
});
