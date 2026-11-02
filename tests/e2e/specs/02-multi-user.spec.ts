import { expect, test } from "@playwright/test";
import { column, createOrgViaUI, createProjectViaUI, quickAddTask, registerViaUI, uniqueEmail } from "./helpers";

test("Scenario 2: invite a second user, assign, realtime sync across sessions, conflicting edits", async ({ browser }) => {
  const ctxA = await browser.newContext();
  const ctxB = await browser.newContext();
  const a = await ctxA.newPage();
  const b = await ctxB.newPage();
  const emailB = uniqueEmail("bob");

  // 1. Two users
  await registerViaUI(a, "Alice Admin", uniqueEmail("alice"));
  await createOrgViaUI(a, "Team Rocket");
  await registerViaUI(b, "Bob Builder", emailB);
  await expect(b.getByRole("heading", { name: "Create your organization" })).toBeVisible();

  // 2. Alice invites Bob via the UI; Bob accepts using the invitation link
  await a.getByRole("link", { name: "Members & settings" }).click();
  await a.getByLabel("Email address").fill(emailB);
  await a.getByLabel("Role").selectOption("member");
  await a.getByRole("button", { name: "Send invite" }).click();
  const inviteUrl = (await a.getByTestId("invite-link").textContent())!.trim();
  expect(inviteUrl).toContain("/invite?token=");
  await b.goto(new URL(inviteUrl).pathname + new URL(inviteUrl).search);
  await expect(b.getByRole("heading", { name: "Join Team Rocket" })).toBeVisible();
  await b.getByRole("button", { name: "Accept invitation" }).click();
  await expect(b).toHaveURL(/\/o\/[0-9a-f-]+\/projects/);

  // Alice creates a project, adds Bob as project member, creates a task and assigns it to Bob
  await a.getByRole("link", { name: "Projects", exact: true }).click();
  await createProjectViaUI(a, "Launch", "LCH");
  const projectUrl = a.url();
  await a.getByRole("link", { name: "Settings", exact: true }).click();
  await a.getByLabel("Add member").selectOption({ label: "Bob Builder (member)" });
  await a.getByRole("button", { name: "Add", exact: true }).click();
  await expect(a.getByRole("listitem").filter({ hasText: emailB })).toBeVisible();
  await a.goto(projectUrl);
  await quickAddTask(a, "To Do", "Write press release");
  await a.getByTestId("task-card").filter({ hasText: "Write press release" }).click();
  const dlgA = a.getByRole("dialog");
  const assigned = a.waitForResponse((r) => r.url().includes("/api/v1/tasks/") && r.request().method() === "PATCH");
  await dlgA.getByRole("checkbox", { name: "Bob Builder" }).click();
  expect((await assigned).status()).toBe(200);
  await expect(dlgA.getByRole("checkbox", { name: "Bob Builder" })).toBeChecked();
  await a.keyboard.press("Escape");

  // 3/4. Bob opens the same board in his session and sees the assignment
  await b.goto(projectUrl);
  await expect(b.getByTestId("connection-status")).toHaveText("Live");
  const bobCard = b.getByTestId("task-card").filter({ hasText: "Write press release" });
  await expect(bobCard.getByRole("img", { name: "Bob Builder" })).toBeVisible();
  // presence: both users visible to each other
  await expect(a.getByTestId("presence").getByRole("img", { name: /Bob Builder/ })).toBeVisible();

  // 5/6. Alice edits in her session -> Bob receives it live, without reloading
  await a.getByTestId("task-card").filter({ hasText: "Write press release" }).click();
  const title = a.getByRole("dialog").getByTestId("task-title-input");
  await title.fill("Write & publish press release");
  await title.press("Enter");
  await a.keyboard.press("Escape");
  await expect(b.getByTestId("task-card").filter({ hasText: "Write & publish press release" })).toBeVisible();
  // Alice creates a new task -> appears for Bob
  await quickAddTask(a, "In Progress", "Book venue");
  await expect(column(b, "In Progress").getByTestId("task-card").filter({ hasText: "Book venue" })).toBeVisible();
  // Bob comments -> Alice sees it live in the open task dialog
  await a.getByTestId("task-card").filter({ hasText: "Book venue" }).click();
  await b.getByTestId("task-card").filter({ hasText: "Book venue" }).click();
  await b.getByRole("dialog").getByPlaceholder("Write a comment…").fill("I can call the venue tomorrow");
  await b.getByRole("dialog").getByRole("button", { name: "Comment" }).click();
  await expect(a.getByRole("dialog").getByTestId("comment").filter({ hasText: "I can call the venue tomorrow" })).toBeVisible();
  await a.keyboard.press("Escape");
  await b.keyboard.press("Escape");

  // 7. Conflicting modifications. Bob's second tab has realtime blocked (simulated
  // network partition), so it keeps a stale copy while Alice saves a change.
  const b2 = await ctxB.newPage();
  await b2.routeWebSocket(/\/api\/v1\/ws/, (ws) => ws.close());
  await b2.goto(projectUrl);
  await b2.getByTestId("task-card").filter({ hasText: "Book venue" }).click();
  const staleTitle = b2.getByRole("dialog").getByTestId("task-title-input");
  await expect(staleTitle).toHaveValue("Book venue");

  await a.getByTestId("task-card").filter({ hasText: "Book venue" }).click();
  const aTitle = a.getByRole("dialog").getByTestId("task-title-input");
  await aTitle.fill("Book venue (Alice)");
  const saved = a.waitForResponse((r) => r.url().includes("/api/v1/tasks/") && r.request().method() === "PATCH");
  await aTitle.press("Enter");
  expect((await saved).status()).toBe(200);
  await a.keyboard.press("Escape");

  await staleTitle.fill("Book venue (Bob)");
  const conflict = b2.waitForResponse((r) => r.url().includes("/api/v1/tasks/") && r.request().method() === "PATCH");
  await staleTitle.press("Enter");
  expect((await conflict).status()).toBe(409); // server detected the lost-update attempt
  const banner = b2.getByTestId("conflict-banner");
  await expect(banner).toContainText("changed by someone else");
  await expect(banner).toContainText("Book venue (Alice)");
  // Bob chooses to overwrite deliberately -> succeeds with the fresh version
  const overwrite = b2.waitForResponse((r) => r.url().includes("/api/v1/tasks/") && r.request().method() === "PATCH");
  await banner.getByRole("button", { name: "Overwrite with my changes" }).click();
  expect((await overwrite).status()).toBe(200);
  await expect(banner).toHaveCount(0);
  // Alice (live) sees Bob's final title
  await expect(a.getByTestId("task-card").filter({ hasText: "Book venue (Bob)" })).toBeVisible();

  await ctxA.close();
  await ctxB.close();
});

test("Realtime: reconnects and recovers updates missed while offline", async ({ browser }) => {
  const ctxA = await browser.newContext();
  const a = await ctxA.newPage();
  await registerViaUI(a, "Rita Realtime", uniqueEmail("rita"));
  await createOrgViaUI(a, "Reconnect Org");
  await createProjectViaUI(a, "Sync", "SYN");
  const url = a.url();
  const ctxB = await browser.newContext({ storageState: await ctxA.storageState() });
  const b = await ctxB.newPage();
  // Proxy B's WebSocket so the test can cut the network link deterministically.
  let blocked = false;
  let current: { close: () => Promise<void> } | null = null;
  await b.routeWebSocket(/\/api\/v1\/ws/, (ws) => {
    if (blocked) {
      void ws.close({ code: 1006 });
      return;
    }
    ws.connectToServer();
    current = ws;
  });
  await b.goto(url);
  await expect(b.getByTestId("connection-status")).toHaveText("Live");
  blocked = true;
  await current!.close();
  await expect(b.getByTestId("connection-status")).toHaveText("Reconnecting…");
  await quickAddTask(a, "To Do", "Created while B offline");
  await expect(b.getByTestId("task-card").filter({ hasText: "Created while B offline" })).toHaveCount(0);
  blocked = false;
  await expect(b.getByTestId("connection-status")).toHaveText("Live", { timeout: 40_000 });
  // The missed event is replayed on resubscribe (no page reload)
  await expect(b.getByTestId("task-card").filter({ hasText: "Created while B offline" })).toBeVisible({ timeout: 15_000 });
  await ctxA.close();
  await ctxB.close();
});
