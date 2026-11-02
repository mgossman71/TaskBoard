import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

export const PASSWORD = "E2e-Passw0rd!secure";

export function uniqueEmail(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@example.com`;
}

export async function registerViaUI(page: Page, name: string, email: string) {
  await page.goto("/register");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
}

export async function loginViaUI(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

export async function createOrgViaUI(page: Page, name: string) {
  await expect(page.getByLabel("New organization name")).toBeVisible();
  await page.getByLabel("New organization name").fill(name);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page).toHaveURL(/\/o\/[0-9a-f-]+\/projects/);
}

export async function createProjectViaUI(page: Page, name: string, key: string) {
  await page.getByRole("button", { name: /New project|Create your first project/ }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Project name").fill(name);
  await dialog.getByLabel("Key").fill(key);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/p\/[0-9a-f-]+\/board/);
  await expect(page.getByTestId("connection-status")).toHaveText("Live");
}

export function column(page: Page, name: string): Locator {
  return page.locator(`[data-testid="column"][data-column-name="${name}"]`);
}

export async function quickAddTask(page: Page, columnName: string, title: string) {
  const col = column(page, columnName);
  await col.getByRole("button", { name: `Add task to ${columnName}` }).click();
  await col.getByLabel(`New task title in ${columnName}`).fill(title);
  await col.getByRole("button", { name: "Add", exact: true }).click();
  await expect(col.getByTestId("task-card").filter({ hasText: title })).toBeVisible();
  await col.getByRole("button", { name: "Cancel" }).click();
}

/** Drag a card onto a column using real pointer events (dnd-kit PointerSensor). */
export async function dragCardToColumn(page: Page, title: string, columnName: string) {
  const card = page.getByTestId("task-card").filter({ hasText: title });
  const target = column(page, columnName).locator(".column-body");
  const from = (await card.boundingBox())!;
  const to = (await target.boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 12, from.y + from.height / 2 + 4, { steps: 4 });
  await page.mouse.move(to.x + to.width / 2, to.y + Math.min(to.height - 10, 40), { steps: 20 });
  await page.waitForTimeout(150);
  await page.mouse.up();
}

export async function apiRegister(request: APIRequestContext, name: string) {
  const email = uniqueEmail(name);
  const r = await request.post("/api/v1/auth/register", { data: { email, password: PASSWORD, display_name: name } });
  expect(r.status()).toBe(201);
  const body = await r.json();
  return { email, token: body.access_token as string, id: body.user.id as string, headers: { Authorization: `Bearer ${body.access_token}` } };
}
