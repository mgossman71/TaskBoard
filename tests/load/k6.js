// ForgeBoard load test: 100 concurrent active users against an org with 10,000 tasks.
// Scenario "api": each VU logs in once (setup) and loops realistic requests.
// Scenario "realtime": 100 WebSocket clients stay subscribed and count events.
import http from "k6/http";
import ws from "k6/ws";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";

const BASE = __ENV.BASE_URL || "http://web:8080";
const WS_BASE = BASE.replace(/^http/, "ws");
const seed = JSON.parse(open(__ENV.SEED || "/load/seed.json"));
const DURATION = __ENV.DURATION || "2m";
const VUS = Number(__ENV.VUS || 100);

const wsEvents = new Counter("ws_events_received");
const listLatency = new Trend("fb_list_tasks", true);
const searchLatency = new Trend("fb_search_tasks", true);
const boardLatency = new Trend("fb_board", true);
const updateLatency = new Trend("fb_update_task", true);
const moveLatency = new Trend("fb_move_task", true);
const dashLatency = new Trend("fb_dashboard", true);
const graphLatency = new Trend("fb_dependency_graph", true);

export const options = {
  setupTimeout: "5m",
  scenarios: {
    api: { executor: "constant-vus", vus: VUS, duration: DURATION, exec: "api" },
    realtime: { executor: "constant-vus", vus: VUS, duration: DURATION, exec: "realtime" },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{scenario:api}": ["p(95)<1000"],
  },
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
};

export function setup() {
  const tokens = [];
  for (const email of seed.emails.slice(0, VUS)) {
    const r = http.post(`${BASE}/api/v1/auth/login`, JSON.stringify({ email, password: seed.password }), {
      headers: { "Content-Type": "application/json" },
    });
    check(r, { "login 200": (x) => x.status === 200 });
    tokens.push(r.json("access_token"));
  }
  const first = { Authorization: `Bearer ${tokens[0]}` };
  const columns = {};
  for (const p of seed.project_ids) {
    columns[p] = http.get(`${BASE}/api/v1/projects/${p}/columns`, { headers: first }).json().map((c) => c.id);
  }
  return { tokens, columns };
}

const WORDS = ["api", "billing", "dashboard", "search", "sync", "upload", "login"];
const PRIORITIES = ["low", "medium", "high", "urgent"];

export function api(data) {
  const token = data.tokens[(__VU - 1) % data.tokens.length];
  const h = { headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } };
  const pid = seed.project_ids[Math.floor(Math.random() * seed.project_ids.length)];

  // Paginated list (2 pages, keyset cursor)
  let r = http.get(`${BASE}/api/v1/projects/${pid}/tasks?limit=50&sort=updated_at&direction=desc`, h);
  listLatency.add(r.timings.duration);
  check(r, { "list 200": (x) => x.status === 200 });
  const page = r.status === 200 ? r.json() : { items: [] };
  if (page.next_cursor) {
    r = http.get(`${BASE}/api/v1/projects/${pid}/tasks?limit=50&sort=updated_at&direction=desc&cursor=${page.next_cursor}`, h);
    listLatency.add(r.timings.duration);
  }
  // Search + filter
  const q = WORDS[Math.floor(Math.random() * WORDS.length)];
  r = http.get(`${BASE}/api/v1/orgs/${seed.org_id}/tasks?q=${q}&priority=${PRIORITIES[__ITER % 4]}&status=open&limit=25&include_total=true`, h);
  searchLatency.add(r.timings.duration);
  check(r, { "search 200": (x) => x.status === 200 });

  // Edit a task (optimistic concurrency: 409 is a legitimate outcome under contention)
  if (page.items.length) {
    const t = page.items[Math.floor(Math.random() * page.items.length)];
    r = http.patch(`${BASE}/api/v1/tasks/${t.id}`, JSON.stringify({ version: t.version, priority: PRIORITIES[__ITER % 4] }), {
      ...h,
      responseCallback: http.expectedStatuses(200, 409),
    });
    updateLatency.add(r.timings.duration);
    check(r, { "update 200/409": (x) => x.status === 200 || x.status === 409 });
    const cols = data.columns[pid];
    const t2 = page.items[Math.floor(Math.random() * page.items.length)];
    r = http.post(
      `${BASE}/api/v1/tasks/${t2.id}/move`,
      JSON.stringify({ version: t2.version, column_id: cols[Math.floor(Math.random() * cols.length)] }),
      { ...h, responseCallback: http.expectedStatuses(200, 409) },
    );
    moveLatency.add(r.timings.duration);
  }
  // Heavier reads, less often
  if (__ITER % 5 === 0) {
    r = http.get(`${BASE}/api/v1/orgs/${seed.org_id}/dashboard`, h);
    dashLatency.add(r.timings.duration);
    check(r, { "dashboard 200": (x) => x.status === 200 });
  }
  if (__ITER % 10 === 0) {
    r = http.get(`${BASE}/api/v1/projects/${pid}/board`, h);
    boardLatency.add(r.timings.duration);
    check(r, { "board 200": (x) => x.status === 200 });
    r = http.get(`${BASE}/api/v1/projects/${pid}/dependency-graph`, h);
    graphLatency.add(r.timings.duration);
    check(r, { "graph 200": (x) => x.status === 200 });
  }
  sleep(1 + Math.random());
}

export function realtime(data) {
  const token = data.tokens[(__VU - 1) % data.tokens.length];
  const pid = seed.project_ids[(__VU - 1) % seed.project_ids.length];
  const res = ws.connect(`${WS_BASE}/api/v1/ws`, { headers: { Origin: BASE } }, (socket) => {
    socket.on("open", () => socket.send(JSON.stringify({ type: "auth", token })));
    socket.on("message", (raw) => {
      const m = JSON.parse(raw);
      if (m.kind === "ready") socket.send(JSON.stringify({ type: "subscribe", project_id: pid }));
      if (m.kind === "event") wsEvents.add(1);
    });
    socket.setInterval(() => socket.send(JSON.stringify({ type: "ping" })), 20000);
    socket.setTimeout(() => socket.close(), 60000);
  });
  check(res, { "ws 101": (r) => r && r.status === 101 });
}
