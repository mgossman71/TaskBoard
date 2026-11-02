import { expect, test, type Page } from "@playwright/test";
import { apiRegister, loginViaUI } from "./helpers";

async function seed(request: Parameters<typeof apiRegister>[0]) {
  const u = await apiRegister(request, "dash");
  const org = await (await request.post("/api/v1/orgs", { data: { name: "Dash Org" }, headers: u.headers })).json();
  const p = await (await request.post(`/api/v1/orgs/${org.id}/projects`, { data: { name: "Metrics", key: "MET" }, headers: u.headers })).json();
  const board = await (await request.get(`/api/v1/projects/${p.id}/board`, { headers: u.headers })).json();
  const done = board.columns.find((c: { is_done: boolean }) => c.is_done).id;
  const today = new Date();
  for (let i = 0; i < 8; i++) {
    const due = new Date(today.getTime() + (i - 3) * 86400000).toISOString().slice(0, 10);
    const t = await (
      await request.post(`/api/v1/projects/${p.id}/tasks`, {
        data: { title: `Task ${i}`, priority: ["low", "high", "urgent", "medium"][i % 4], due_date: due, assignee_ids: i % 2 ? [u.id] : [] },
        headers: u.headers,
      })
    ).json();
    if (i % 3 === 0) await request.post(`/api/v1/tasks/${t.id}/move`, { data: { version: 1, column_id: done }, headers: u.headers });
  }
  return { u, org, p };
}

function collectErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  return errors;
}

test("Dashboard, list view, themes and mobile layout render without errors", async ({ request, page }) => {
  const { u, org, p } = await seed(request);
  const errors = collectErrors(page);
  await loginViaUI(page, u.email);
  await page.goto(`/o/${org.id}/dashboard`);
  const stats = page.getByTestId("stats");
  await expect(stats).toContainText("Total tasks");
  await expect(stats).toContainText("8");
  await expect(page.locator(".recharts-bar-rectangle").first()).toBeVisible();
  await expect(page.locator(".recharts-line-curve").first()).toBeVisible();
  await expect(page.getByTestId("workload")).toContainText("dash");
  await page.screenshot({ path: "test-results/screens/dashboard-light.png", fullPage: true });

  await page.getByRole("button", { name: /Theme/ }).click();
  await page.getByRole("menuitem", { name: /Dark/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: "test-results/screens/dashboard-dark.png", fullPage: true });

  await page.goto(`/o/${org.id}/p/${p.id}/list?sort=due_date&dir=asc`);
  await expect(page.getByTestId("task-table").locator("tbody tr")).toHaveCount(8);
  await page.getByLabel("Show").selectOption("overdue");
  await expect(page.getByTestId("task-table").locator("tbody tr")).toHaveCount(2);
  await page.screenshot({ path: "test-results/screens/list-dark.png", fullPage: true });

  await page.goto(`/o/${org.id}/p/${p.id}/board`);
  await page.getByTestId("task-card").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({ path: "test-results/screens/task-dialog-dark.png" });
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: /Theme/ }).click();
  await page.getByRole("menuitem", { name: /Light/ }).click();
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
  await page.screenshot({ path: "test-results/screens/board-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();
  await page.screenshot({ path: "test-results/screens/nav-mobile.png" });
  // theme persisted across reload
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(errors, errors.join("\n")).toEqual([]);
});
