// MON-01, MON-02 and MON-03 in the browser, as the admin.
import { expect, test } from "@playwright/test";
import { login, registerPatient } from "./helpers";

test("MON-01..03: the admin sees the dashboard, every service healthy and a case's history", async ({ browser, page }) => {
  // The test makes its own case, so it does not depend on data left by other tests.
  const nurse = await browser.newPage();
  await login(nurse, "nurse");
  const mrn = await registerPatient(nurse);
  await nurse.close();

  await login(page, "admin");
  await expect(page.getByRole("heading", { name: "Monitoring" })).toBeVisible(); // admins land here
  await expect(page.locator(".tile").filter({ hasText: "Active cases" })).toBeVisible();

  await page.getByRole("link", { name: "Services" }).click();
  for (const service of ["gateway", "worklist", "ml", "scores"]) {
    await expect(page.getByRole("row", { name: new RegExp(`^${service} ok`) })).toBeVisible();
  }

  await page.getByRole("link", { name: "Cases" }).click();
  const row = page.locator("tbody tr").filter({ hasText: mrn }).first();
  await expect(async () => {
    await page.getByRole("link", { name: "Services" }).click(); // reopen Cases to reload the list
    await page.getByRole("link", { name: "Cases" }).click();
    await expect(row).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await row.click();
  await expect(page.getByRole("heading", { name: /History \(\d+ events\)/ })).toBeVisible();
  await expect(page.locator(".timeline li").first()).toContainText("Case started");
});
