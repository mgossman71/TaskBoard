import { describe, expect, it } from "vitest";
import { passwordSchema, projectSchema, registerSchema } from "./validation";

describe("validation mirrors server rules", () => {
  it.each([
    ["short1!A", false],
    ["alllowercaseletters", false],
    ["lowercase123456", false],
    ["Lowercase123456", true],
    ["lower-case-symbols-1", true],
  ])("password %s valid=%s", (pw, ok) => {
    expect(passwordSchema.safeParse(pw).success).toBe(ok);
  });

  it("requires matching confirmation", () => {
    const r = registerSchema.safeParse({ display_name: "A", email: "a@example.com", password: "Valid-Passw0rd", confirm: "nope" });
    expect(r.success).toBe(false);
    expect(r.error!.issues[0].path).toEqual(["confirm"]);
  });

  it("validates project keys", () => {
    expect(projectSchema.safeParse({ name: "X", key: "WEB", description: "" }).success).toBe(true);
    expect(projectSchema.safeParse({ name: "X", key: "web", description: "" }).success).toBe(false);
    expect(projectSchema.safeParse({ name: "X", key: "1AB", description: "" }).success).toBe(false);
    expect(projectSchema.safeParse({ name: " ", key: "AB", description: "" }).success).toBe(false);
  });
});
