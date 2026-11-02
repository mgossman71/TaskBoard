import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RealtimeClient, type ProjectMessage } from "./realtime";
import { setTokens } from "./api";

class FakeWS {
  static OPEN = 1;
  static instances: FakeWS[] = [];
  readyState = 0;
  sent: any[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  send(d: string) {
    this.sent.push(JSON.parse(d));
  }
  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  push(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

const token = { access_token: "tok", token_type: "bearer", expires_at: new Date(Date.now() + 600_000).toISOString(), user: { id: "u", email: "", display_name: "", created_at: "" } };

describe("RealtimeClient", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWS.instances = [];
    vi.stubGlobal("WebSocket", FakeWS);
    setTokens(token);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    setTokens(null);
  });

  it("authenticates with the first message, subscribes with the replay cursor, dedupes events", () => {
    const socks: FakeWS[] = [];
    const rt = new RealtimeClient((u) => {
      const w = new FakeWS(u);
      socks.push(w);
      return w as unknown as WebSocket;
    });
    const got: ProjectMessage[] = [];
    const unsub = rt.subscribe("p1", 41, (m) => got.push(m));
    const ws = socks[0];
    expect(ws.url).toMatch(/\/api\/v1\/ws$/);
    ws.open();
    expect(ws.sent[0]).toEqual({ type: "auth", token: "tok" });
    ws.push({ kind: "ready" });
    expect(rt.status).toBe("connected");
    expect(ws.sent[1]).toEqual({ type: "subscribe", project_id: "p1", since: 41 });
    const ev = { kind: "event", id: 42, type: "task.created", project_id: "p1", payload: {} };
    ws.push(ev);
    ws.push(ev); // duplicate (e.g. replay overlap) is dropped
    ws.push({ ...ev, id: 43, project_id: "other" }); // not subscribed
    expect(got.filter((m) => m.kind === "event")).toHaveLength(1);
    expect(rt.lastEventId("p1")).toBe(42);
    unsub();
  });

  it("reconnects with backoff and resumes from the last seen event", () => {
    const socks: FakeWS[] = [];
    const rt = new RealtimeClient((u) => {
      const w = new FakeWS(u);
      socks.push(w);
      return w as unknown as WebSocket;
    });
    const unsub = rt.subscribe("p1", 0, () => undefined);
    const ws1 = socks[0];
    ws1.open();
    ws1.push({ kind: "ready" });
    ws1.push({ kind: "event", id: 7, type: "task.updated", project_id: "p1", payload: {} });
    ws1.close(1006);
    expect(rt.status).toBe("reconnecting");
    vi.advanceTimersByTime(1000);
    const ws2 = socks[1];
    expect(ws2).toBeDefined();
    ws2.open();
    ws2.push({ kind: "ready" });
    expect(ws2.sent).toContainEqual({ type: "subscribe", project_id: "p1", since: 7 });
    expect(rt.status).toBe("connected");
    unsub();
  });

  it("forwards presence, resync and access revocation", () => {
    const socks: FakeWS[] = [];
    const rt = new RealtimeClient((u) => {
      const w = new FakeWS(u);
      socks.push(w);
      return w as unknown as WebSocket;
    });
    const got: ProjectMessage[] = [];
    const unsub = rt.subscribe("p1", 0, (m) => got.push(m));
    const ws = socks[0];
    ws.open();
    ws.push({ kind: "ready" });
    ws.push({ kind: "presence", project_id: "p1", users: [{ user_id: "x", display_name: "X", viewing_task_ids: [] }] });
    ws.push({ kind: "resync_required", project_id: "p1" });
    ws.push({ kind: "unsubscribed", project_id: "p1", reason: "access_revoked" });
    expect(got.map((m) => m.kind)).toEqual(["presence", "resync", "revoked"]);
    unsub();
  });

  it("sends a heartbeat and re-authenticates when the token rotates", () => {
    const socks: FakeWS[] = [];
    const rt = new RealtimeClient((u) => {
      const w = new FakeWS(u);
      socks.push(w);
      return w as unknown as WebSocket;
    });
    const unsub = rt.subscribe("p1", 0, () => undefined);
    const ws = socks[0];
    ws.open();
    ws.push({ kind: "ready" });
    vi.advanceTimersByTime(20_500);
    expect(ws.sent).toContainEqual({ type: "ping" });
    setTokens({ ...token, access_token: "tok2" });
    expect(ws.sent).toContainEqual({ type: "reauth", token: "tok2" });
    unsub();
  });
});
