// VER-01 and NFR-USE-01 in the browser: the deadlock is found, shown and replayable.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("VER-01: the imaging deadlock is UNSAFE and its counterexample replays step by step", async ({ page }) => {
  await login(page, "designer");
  await page.getByRole("row", { name: /Imaging \(has a deadlock\)/ }).click();
  const started = Date.now();
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.locator(".report .badge-unsafe")).toHaveText("UNSAFE");
  expect(Date.now() - started).toBeLessThan(2000); // NFR-USE-01: errors on the canvas within 2 s
  await expect(page.locator(".errors li").filter({ hasText: "Deadlock" })).toContainText("wait_both");
  const position = page.getByLabel("Replay position");
  await expect(position).toBeVisible();
  await page.getByTitle("First move").click();
  await page.getByTitle("Next move").click();
  await page.getByTitle("Last move").click();
  await expect(page.getByTitle("Last move")).toBeDisabled();
});
