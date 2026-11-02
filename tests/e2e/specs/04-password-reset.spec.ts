import { expect, test } from "@playwright/test";
import { PASSWORD, apiRegister } from "./helpers";

const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";

test("Password reset via emailed link (SMTP -> Mailpit)", async ({ request, page }) => {
  const u = await apiRegister(request, "forgetful");
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(u.email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("status")).toContainText("reset link is on its way");

  let link = "";
  await expect
    .poll(
      async () => {
        const res = await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${u.email}`)}`);
        const data = await res.json();
        if (!data.messages?.length) return "";
        const msg = await (await request.get(`${MAILPIT}/api/v1/message/${data.messages[0].ID}`)).json();
        link = (msg.Text as string).match(/https?:\/\/\S+reset-password\?token=\S+/)?.[0] ?? "";
        return link;
      },
      { timeout: 15_000 },
    )
    .toContain("reset-password?token=");

  const target = new URL(link);
  await page.goto(target.pathname + target.search);
  const newPw = "N3w-Passw0rd!reset";
  await page.getByLabel("New password", { exact: true }).fill(newPw);
  await page.getByLabel("Confirm new password").fill(newPw);
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(page.getByText("Your password has been changed.")).toBeVisible();
  // old session revoked, old password rejected, new one works
  expect((await request.get("/api/v1/auth/me", { headers: u.headers })).status()).toBe(401);
  expect((await request.post("/api/v1/auth/login", { data: { email: u.email, password: PASSWORD } })).status()).toBe(401);
  expect((await request.post("/api/v1/auth/login", { data: { email: u.email, password: newPw } })).status()).toBe(200);
});
