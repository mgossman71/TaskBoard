import { expect, test } from "@playwright/test";
import { apiRegister, loginViaUI } from "./helpers";

test("Scenario 3: cross-organization access is rejected and leaks nothing", async ({ request, page }) => {
  // 1/2. Two separate organizations with projects and tasks
  const alice = await apiRegister(request, "alice-sec");
  const mallory = await apiRegister(request, "mallory");
  const orgA = await (await request.post("/api/v1/orgs", { data: { name: "Alpha Confidential" }, headers: alice.headers })).json();
  const orgM = await (await request.post("/api/v1/orgs", { data: { name: "Mallory Corp" }, headers: mallory.headers })).json();
  const projA = await (await request.post(`/api/v1/orgs/${orgA.id}/projects`, { data: { name: "Secret Plans", key: "SEC" }, headers: alice.headers })).json();
  const projM = await (await request.post(`/api/v1/orgs/${orgM.id}/projects`, { data: { name: "Mallory Project", key: "MAL" }, headers: mallory.headers })).json();
  const taskA = await (await request.post(`/api/v1/projects/${projA.id}/tasks`, { data: { title: "Acquire competitor", description: "codename: falcon" }, headers: alice.headers })).json();
  const taskM = await (await request.post(`/api/v1/projects/${projM.id}/tasks`, { data: { title: "Mallory task" }, headers: mallory.headers })).json();
  expect(taskA.id && taskM.id).toBeTruthy();

  // 3/4. Mallory attempts to read and modify Alice's data through the API
  const attempts: [string, string, unknown?][] = [
    ["GET", `/api/v1/orgs/${orgA.id}`],
    ["GET", `/api/v1/orgs/${orgA.id}/members`],
    ["GET", `/api/v1/orgs/${orgA.id}/projects`],
    ["GET", `/api/v1/orgs/${orgA.id}/tasks?q=competitor`],
    ["GET", `/api/v1/orgs/${orgA.id}/dashboard`],
    ["GET", `/api/v1/orgs/${orgA.id}/activity`],
    ["GET", `/api/v1/projects/${projA.id}/board`],
    ["GET", `/api/v1/projects/${projA.id}/tasks`],
    ["GET", `/api/v1/projects/${projA.id}/activity`],
    ["GET", `/api/v1/tasks/${taskA.id}`],
    ["GET", `/api/v1/tasks/${taskA.id}/history`],
    ["PATCH", `/api/v1/tasks/${taskA.id}`, { version: 1, title: "pwned" }],
    ["DELETE", `/api/v1/tasks/${taskA.id}`],
    ["POST", `/api/v1/projects/${projA.id}/tasks`, { title: "injected" }],
    ["POST", `/api/v1/tasks/${taskA.id}/comments`, { body: "hi" }],
    ["POST", `/api/v1/orgs/${orgA.id}/invitations`, { email: "mallory2@example.com", role: "admin" }],
    ["DELETE", `/api/v1/projects/${projA.id}`],
    ["POST", `/api/v1/tasks/${taskM.id}/dependencies`, { depends_on_id: taskA.id }],
  ];
  for (const [method, url, data] of attempts) {
    const r = await request.fetch(url, { method, data, headers: mallory.headers });
    expect(r.status(), `${method} ${url}`).toBe(404);
    // 5. no sensitive information in the response
    const text = await r.text();
    for (const secret of ["Alpha", "Secret", "competitor", "falcon", alice.email]) expect(text).not.toContain(secret);
  }
  // Unauthenticated access is rejected too
  expect((await request.get(`/api/v1/tasks/${taskA.id}`)).status()).toBe(401);

  // Alice's data is untouched
  const check = await (await request.get(`/api/v1/tasks/${taskA.id}`, { headers: alice.headers })).json();
  expect(check.title).toBe("Acquire competitor");
  expect(check.comments).toHaveLength(0);

  // In the UI, Mallory navigating to Alice's project URL gets a not-found state, no data
  await loginViaUI(page, mallory.email);
  await expect(page).toHaveURL(/\/o\//);
  await page.goto(`/o/${orgA.id}/p/${projA.id}/board`);
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await expect(page.getByText("Secret Plans")).toHaveCount(0);
  await expect(page.getByText("Acquire competitor")).toHaveCount(0);
});

test("Viewer role is read-only in the UI and API", async ({ request, page }) => {
  const owner = await apiRegister(request, "owner-ro");
  const viewer = await apiRegister(request, "viewer-ro");
  const org = await (await request.post("/api/v1/orgs", { data: { name: "RO Org" }, headers: owner.headers })).json();
  const inv = await (await request.post(`/api/v1/orgs/${org.id}/invitations`, { data: { email: viewer.email, role: "viewer" }, headers: owner.headers })).json();
  const token = new URL(inv.invite_url).searchParams.get("token");
  expect((await request.post("/api/v1/invitations/accept", { data: { token }, headers: viewer.headers })).status()).toBe(200);
  const proj = await (await request.post(`/api/v1/orgs/${org.id}/projects`, { data: { name: "Readonly", key: "RO", member_ids: [viewer.id] }, headers: owner.headers })).json();
  await request.post(`/api/v1/projects/${proj.id}/tasks`, { data: { title: "Look but don't touch" }, headers: owner.headers });
  expect((await request.post(`/api/v1/projects/${proj.id}/tasks`, { data: { title: "x" }, headers: viewer.headers })).status()).toBe(403);
  await loginViaUI(page, viewer.email);
  await page.goto(`/o/${org.id}/p/${proj.id}/board`);
  await expect(page.getByTestId("task-card").filter({ hasText: "Look but don't touch" })).toBeVisible();
  await expect(page.getByText("Read-only")).toBeVisible();
  await expect(page.getByRole("button", { name: /Add task to/ })).toHaveCount(0);
});
