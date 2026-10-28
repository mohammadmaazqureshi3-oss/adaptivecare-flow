// AUTH-01 in the browser: deactivating a user locks them out, so the admin must confirm it.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("AUTH-01: deactivating a user needs a confirmation; cancelling keeps them active", async ({ page }) => {
  await login(page, "admin");
  await page.getByRole("link", { name: "Users" }).click();
  const row = page.getByRole("row").filter({ hasText: "designer@adaptivecare.test" });
  await expect(row).toContainText("Active");

  page.once("dialog", (d) => {
    expect(d.message()).toContain("will no longer be able to sign in");
    void d.dismiss();
  });
  await row.getByRole("button", { name: "Deactivate" }).click();
  await expect(row).toContainText("Active"); // cancelled: nothing changed
  await expect(row.getByRole("button", { name: "Deactivate" })).toBeVisible();

  page.once("dialog", (d) => void d.accept());
  await row.getByRole("button", { name: "Deactivate" }).click();
  await expect(row).toContainText("Deactivated");
  await row.getByRole("button", { name: "Reactivate" }).click(); // no confirmation needed to undo
  await expect(row.getByRole("button", { name: "Deactivate" })).toBeVisible();
});
