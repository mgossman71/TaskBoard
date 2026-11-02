import { expect, test } from "@playwright/test";
import { column, createOrgViaUI, createProjectViaUI, dragCardToColumn, loginViaUI, quickAddTask, registerViaUI, uniqueEmail } from "./helpers";

test("Scenario 1: register, log in, create org/project/task, move it, persists after refresh", async ({ page }) => {
  const email = uniqueEmail("founder");
  // 1. Register
  await registerViaUI(page, "Fiona Founder", email);
  await expect(page.getByRole("heading", { name: "Create your organization" })).toBeVisible();
  // 2. Log out and log in again
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await loginViaUI(page, email);
  // 3. Create organization
  await createOrgViaUI(page, "Founders Inc");
  await expect(page.getByRole("heading", { name: "No projects yet" })).toBeVisible();
  // 4. Create project
  await createProjectViaUI(page, "Website Relaunch", "WEB");
  await expect(column(page, "To Do")).toBeVisible();
  // 5. Create task
  await quickAddTask(page, "To Do", "Design landing page");
  // 6. Drag it into "In Progress" (real pointer drag); wait for the server to confirm
  const moved = page.waitForResponse((r) => r.url().includes("/move") && r.request().method() === "POST");
  await dragCardToColumn(page, "Design landing page", "In Progress");
  expect((await moved).status()).toBe(200);
  await expect(column(page, "In Progress").getByTestId("task-card").filter({ hasText: "Design landing page" })).toBeVisible();
  await expect(column(page, "To Do").getByTestId("task-card")).toHaveCount(0);
  // 7. Refresh: change persisted
  await page.reload();
  await expect(column(page, "In Progress").getByTestId("task-card").filter({ hasText: "Design landing page" })).toBeVisible();
  await expect(column(page, "To Do").getByTestId("task-card")).toHaveCount(0);

  // Also move via the task dialog's Status select (keyboard-accessible alternative) into Done
  await page.getByTestId("task-card").filter({ hasText: "Design landing page" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByTestId("task-status-select").selectOption({ label: "Done" });
  await expect(dialog.getByText("Done", { exact: true }).first()).toBeVisible();
  await page.keyboard.press("Escape");
  await page.reload();
  await expect(column(page, "Done").getByTestId("task-card").filter({ hasText: "Design landing page" })).toBeVisible();
  // Route survives a hard refresh on a deep link (nginx SPA fallback)
  await expect(page.getByRole("heading", { name: "Website Relaunch" })).toBeVisible();
});
