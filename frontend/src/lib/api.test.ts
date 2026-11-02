import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, getAccessToken, refreshSession, setSessionExpiredHandler, setTokens } from "./api";

const tokenResp = (t: string) => ({
  access_token: t,
  token_type: "bearer",
  expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
  user: { id: "u", email: "u@example.com", display_name: "U", created_at: "" },
});
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("api client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    document.cookie = "fb_csrf=csrf123";
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setTokens(tokenResp("old"));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setTokens(null);
    setSessionExpiredHandler(null);
  });

  it("attaches the bearer token and parses JSON", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    await expect(api.get("/x", { a: 1, b: ["p", "q"], skip: undefined })).resolves.toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/x?a=1&b=p&b=q");
    expect(init.headers.Authorization).toBe("Bearer old");
  });

  it("refreshes once for concurrent 401s, then retries each request", async () => {
    let refreshCalls = 0;
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (url === "/api/v1/auth/refresh") {
        refreshCalls++;
        expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf123");
        await new Promise((r) => setTimeout(r, 10));
        return json(200, tokenResp("new"));
      }
      const auth = (init.headers as Record<string, string>).Authorization;
      return auth === "Bearer new" ? json(200, { url }) : json(401, { error: { code: "unauthorized", message: "expired" } });
    });
    const results = await Promise.all([api.get("/a"), api.get("/b"), api.get("/c")]);
    expect(results).toEqual([{ url: "/api/v1/a" }, { url: "/api/v1/b" }, { url: "/api/v1/c" }]);
    expect(refreshCalls).toBe(1);
    expect(getAccessToken()).toBe("new");
  });

  it("signals session expiry when refresh fails", async () => {
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    fetchMock.mockImplementation(async (url: string) =>
      url === "/api/v1/auth/refresh" ? json(401, { error: { code: "unauthorized", message: "no" } }) : json(401, { error: { code: "unauthorized", message: "no" } }),
    );
    await expect(api.get("/a")).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
  });

  it("returns null from refreshSession without a CSRF cookie", async () => {
    document.cookie = "fb_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    await expect(refreshSession()).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("exposes structured errors, conflicts and field errors", async () => {
    fetchMock.mockResolvedValueOnce(json(409, { error: { code: "version_conflict", message: "changed", details: { current: { version: 3 } } } }));
    const err = (await api.patch("/tasks/1", {}).catch((e) => e)) as ApiError;
    expect(err.isConflict).toBe(true);
    expect((err.details as { current: { version: number } }).current.version).toBe(3);
    fetchMock.mockResolvedValueOnce(json(422, { error: { code: "validation_error", message: "bad", details: [{ loc: ["body", "title"], msg: "too long" }] } }));
    const v = (await api.post("/x", {}).catch((e) => e)) as ApiError;
    expect(v.fieldErrors()).toEqual({ title: "too long" });
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const n = (await api.get("/x").catch((e) => e)) as ApiError;
    expect(n.code).toBe("network_error");
  });
});
