/**
 * WebSocket client with authentication, per-project subscriptions, automatic
 * reconnection (exponential backoff + jitter), heartbeat, and gap recovery:
 * on reconnect each subscription resumes from the last event id it saw and the
 * server replays everything missed (or asks for a full resync).
 */
import { getAccessToken, onTokenChange, refreshSession } from "./api";
import type { PresenceUser } from "./types";

export type ConnectionStatus = "idle" | "connecting" | "connected" | "reconnecting" | "offline";

export interface ServerEvent {
  kind: "event";
  id: number;
  type: string;
  org_id: string;
  project_id: string | null;
  task_id: string | null;
  actor_id: string | null;
  actor: { id: string; display_name: string } | null;
  payload: Record<string, any>;
  created_at: string;
}

export type ProjectMessage =
  | { kind: "event"; event: ServerEvent }
  | { kind: "presence"; users: PresenceUser[] }
  | { kind: "resync" }
  | { kind: "revoked" }
  | { kind: "deleted" }
  | { kind: "subscribed"; replayed: number };

type ProjectListener = (msg: ProjectMessage) => void;

interface Subscription {
  listeners: Set<ProjectListener>;
  lastEventId: number;
  seen: Set<number>;
  viewing: string | null;
}

const HEARTBEAT_MS = 20_000;

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private subs = new Map<string, Subscription>();
  private statusListeners = new Set<(s: ConnectionStatus) => void>();
  private _status: ConnectionStatus = "idle";
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private heartbeat: ReturnType<typeof setInterval> | undefined;
  private stopped = true;
  private wsFactory: (url: string) => WebSocket;

  constructor(wsFactory?: (url: string) => WebSocket) {
    this.wsFactory = wsFactory ?? ((url) => new WebSocket(url));
    onTokenChange((token) => {
      if (!token) this.stop();
      else if (this.ws?.readyState === WebSocket.OPEN) this.send({ type: "reauth", token });
      else if (this.stopped && this.subs.size) this.start();
    });
    if (typeof window !== "undefined") {
      window.addEventListener("online", () => this.reconnectNow());
      window.addEventListener("offline", () => this.setStatus("offline"));
    }
  }

  get status() {
    return this._status;
  }

  onStatus(fn: (s: ConnectionStatus) => void) {
    this.statusListeners.add(fn);
    fn(this._status);
    return () => {
      this.statusListeners.delete(fn);
    };
  }

  private setStatus(s: ConnectionStatus) {
    this._status = s;
    this.statusListeners.forEach((l) => l(s));
  }

  /** Subscribe to a project. `since` is the last event id already reflected in local state. */
  subscribe(projectId: string, since: number, fn: ProjectListener): () => void {
    let sub = this.subs.get(projectId);
    if (!sub) {
      sub = { listeners: new Set(), lastEventId: since, seen: new Set(), viewing: null };
      this.subs.set(projectId, sub);
      if (this.ws?.readyState === WebSocket.OPEN && this._status === "connected") {
        this.send({ type: "subscribe", project_id: projectId, since: sub.lastEventId });
      }
    } else if (since > sub.lastEventId) {
      sub.lastEventId = since;
    }
    sub.listeners.add(fn);
    this.start();
    return () => {
      const s = this.subs.get(projectId);
      if (!s) return;
      s.listeners.delete(fn);
      if (s.listeners.size === 0) {
        this.subs.delete(projectId);
        this.send({ type: "unsubscribe", project_id: projectId });
        if (this.subs.size === 0) this.stop();
      }
    };
  }

  setViewing(projectId: string, taskId: string | null) {
    const sub = this.subs.get(projectId);
    if (!sub) return;
    sub.viewing = taskId;
    this.send({ type: "presence", project_id: projectId, viewing_task_id: taskId });
  }

  start() {
    if (!this.stopped) return;
    if (!getAccessToken()) return;
    this.stopped = false;
    this.connect();
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.reconnectTimer);
    clearInterval(this.heartbeat);
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState <= WebSocket.OPEN) ws.close(1000);
    this.setStatus("idle");
  }

  private reconnectNow() {
    if (this.stopped) return;
    clearTimeout(this.reconnectTimer);
    this.attempt = 0;
    if (!this.ws || this.ws.readyState > WebSocket.OPEN) this.connect();
  }

  private send(msg: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private connect() {
    const token = getAccessToken();
    if (!token || this.stopped) return;
    this.setStatus(this.attempt === 0 && this._status !== "reconnecting" ? "connecting" : "reconnecting");
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = this.wsFactory(`${proto}//${window.location.host}/api/v1/ws`);
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: getAccessToken() }));
    ws.onmessage = (e) => this.handle(JSON.parse(e.data));
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      clearInterval(this.heartbeat);
      this.ws = null;
      if (this.stopped) return;
      if (e.code === 4401) {
        // Token expired or session revoked: try to refresh once, otherwise stop.
        refreshSession()
          .then((resp) => (resp ? this.scheduleReconnect(true) : this.stop()))
          .catch(() => this.scheduleReconnect());
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(immediate = false) {
    if (this.stopped) return;
    this.setStatus(typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "reconnecting");
    const base = Math.min(30_000, 500 * 2 ** this.attempt);
    const delay = immediate ? 0 : base / 2 + Math.random() * (base / 2);
    this.attempt += 1;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private handle(msg: any) {
    switch (msg.kind) {
      case "ready":
        this.attempt = 0;
        this.setStatus("connected");
        clearInterval(this.heartbeat);
        this.heartbeat = setInterval(() => this.send({ type: "ping" }), HEARTBEAT_MS);
        for (const [pid, sub] of this.subs) {
          this.send({ type: "subscribe", project_id: pid, since: sub.lastEventId });
          if (sub.viewing) this.send({ type: "presence", project_id: pid, viewing_task_id: sub.viewing });
        }
        break;
      case "event": {
        const pid = msg.project_id as string | null;
        const sub = pid ? this.subs.get(pid) : undefined;
        if (!sub) return;
        if (sub.seen.has(msg.id)) return; // duplicate (replay overlap)
        sub.seen.add(msg.id);
        if (sub.seen.size > 2000) sub.seen = new Set([...sub.seen].slice(-1000));
        sub.lastEventId = Math.max(sub.lastEventId, msg.id);
        sub.listeners.forEach((l) => l({ kind: "event", event: msg as ServerEvent }));
        break;
      }
      case "presence":
        this.subs.get(msg.project_id)?.listeners.forEach((l) => l({ kind: "presence", users: msg.users }));
        break;
      case "subscribed": {
        const sub = this.subs.get(msg.project_id);
        sub?.listeners.forEach((l) => {
          l({ kind: "subscribed", replayed: msg.replayed });
          if (msg.presence) l({ kind: "presence", users: msg.presence });
        });
        break;
      }
      case "resync_required":
        this.subs.get(msg.project_id)?.listeners.forEach((l) => l({ kind: "resync" }));
        break;
      case "unsubscribed":
        if (msg.reason === "access_revoked") this.subs.get(msg.project_id)?.listeners.forEach((l) => l({ kind: "revoked" }));
        break;
      case "project_deleted":
        this.subs.get(msg.project_id)?.listeners.forEach((l) => l({ kind: "deleted" }));
        break;
      case "error":
        if (msg.code === "subscription_denied" && msg.project_id) {
          this.subs.get(msg.project_id)?.listeners.forEach((l) => l({ kind: "revoked" }));
        }
        break;
      default:
        break;
    }
  }

  /** Test helper: last event id tracked for a project. */
  lastEventId(projectId: string) {
    return this.subs.get(projectId)?.lastEventId ?? 0;
  }
}

export const realtime = new RealtimeClient();
