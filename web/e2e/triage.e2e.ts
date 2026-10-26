// PAT-01, CLN-01, CLN-04, ML-02, WRK-01 and WRK-02 in the browser: a nurse registers a patient,
// enters the vital signs, sees the NEWS2 score and the model's suggestion, and can change the
// level only with a reason.
import { expect, test } from "@playwright/test";
import { login, taskCard } from "./helpers";

test("CLN-01: a registered patient goes through triage with NEWS2, the model and an override", async ({ page }) => {
  await login(page, "nurse");
  await expect(page.getByRole("link", { name: "Pathways" })).toHaveCount(0); // AUTH-03: not for nurses

  await page.getByRole("link", { name: "Patients" }).click();
  await page.getByLabel("Full name").fill(`E2E Patient ${Date.now()}`);
  await page.getByLabel("Date of birth").fill("1950-01-01");
  await page.getByLabel("Arrival").selectOption("ambulance");
  await page.getByLabel("Chief complaint").fill("chest pain, short of breath");
  const registered = page.waitForResponse((r) => r.url().endsWith("/api/patients") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Register" }).click();
  const mrn: string = (await (await registered).json()).mrn;

  await page.getByRole("link", { name: "Tasks" }).click();
  const vitals = taskCard(page, mrn, "Measure vital signs");
  await vitals.getByRole("button", { name: "Claim" }).click();
  const values: Record<string, string> = { spo2: "86", sbp: "95", hr: "120", rr: "28", temp: "37.2", pain: "8" };
  for (const [name, value] of Object.entries(values)) await vitals.getByLabel(new RegExp(`^${name}\\b`)).fill(value);
  await vitals.getByLabel(/^mental\b/).fill("alert");
  await vitals.getByRole("button", { name: "Complete" }).click();

  // The scores and ml services answer; the safety rule routes to the urgent confirmation.
  const confirm = taskCard(page, mrn, "Confirm urgency (urgent)");
  await confirm.getByRole("button", { name: "Claim" }).click({ timeout: 60_000 });
  await expect(confirm.locator(".ml-note")).toContainText("ML urgency-v1");
  await expect(confirm).toContainText(/news2: 1\d/);
  await expect(confirm).toContainText("news2_risk: high");

  const suggested = Number((await confirm.locator(".task-inputs").innerText()).match(/urgency: (\d)/)![1]);
  await confirm.getByLabel(/^confirmed_urgency\b/).fill(String(suggested === 1 ? 2 : 1));
  const reason = confirm.getByLabel(/Reason for changing the suggested urgency/);
  await expect(reason).toBeVisible(); // WRK-02: a changed level asks for a reason
  await reason.fill("Grey and clammy, worsening chest pain");
  await confirm.getByRole("button", { name: "Complete" }).click();
  await expect(confirm).toHaveCount(0);
});
