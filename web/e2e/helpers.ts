import { expect, type Page } from "@playwright/test";

// Development fixture accounts created by scripts/seed_demo.py (never real credentials).
export const ACCOUNTS = {
  designer: ["designer@adaptivecare.test", "designer-demo-1"],
  nurse: ["nurse@adaptivecare.test", "nurse-demo-1"],
  admin: ["admin@adaptivecare.test", "admin-demo-1"],
} as const;

export async function login(page: Page, who: keyof typeof ACCOUNTS): Promise<void> {
  const [email, password] = ACCOUNTS[who];
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}

/** The task card for one patient and one task label. */
export function taskCard(page: Page, mrn: string, label: string) {
  return page.locator(".card.task").filter({ hasText: mrn }).filter({ hasText: label });
}
