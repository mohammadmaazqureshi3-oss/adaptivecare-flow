// MON-01, MON-02 and MON-03 in the browser, as the admin.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("MON-01..03: the admin sees the dashboard, every service healthy and a case's history", async ({ page }) => {
  await login(page, "admin");
  await expect(page.getByRole("heading", { name: "Monitoring" })).toBeVisible(); // admins land here
  await expect(page.locator(".tile").filter({ hasText: "Active cases" })).toBeVisible();

  await page.getByRole("link", { name: "Services" }).click();
  for (const service of ["gateway", "worklist", "ml", "scores"]) {
    await expect(page.getByRole("row", { name: new RegExp(`^${service} ok`) })).toBeVisible();
  }

  await page.getByRole("link", { name: "Cases" }).click();
  await page.locator("tbody tr").first().click();
  await expect(page.getByRole("heading", { name: /History \(\d+ events\)/ })).toBeVisible();
  await expect(page.locator(".timeline li").first()).toContainText("Case started");
});
