# Known Issues and Limitations

Honest list of what is incomplete, unverified, or a deliberate trade-off.

## Verification gaps

1. **Not run on a physical Ubuntu 24.04 host.** All testing ran on macOS (Apple Silicon) with
   Docker Desktop 29.8 / Compose v5.5. Both images were cross-built for `linux/amd64` and the API
   image was import-smoke-tested under x86-64 emulation, but the full stack was not executed on
   Ubuntu/amd64 hardware. Nothing host-specific is used (only Docker, bash, curl).
2. **Load test ran on a single machine** (k6, nginx, API, PostgreSQL and Redis all sharing one
   Mac mini, 12 CPUs, 8 GB Docker VM). The load overlay uses `WEB_CONCURRENCY=4` (production
   default is 2). Numbers are indicative for this hardware, not a capacity guarantee.
3. **Horizontal scaling of the API** (`docker compose up --scale api=N`) is designed for (stateless
   workers, Redis fan-out, advisory-locked migrations) but was not tested with multiple API
   containers; multi-*worker* (4 processes) was exercised by the load test.

## Functional limitations

4. **Large boards load every card.** The board endpoint returns all cards of a project (compact
   schema, gzip). Under the 100-user load test, boards of 2,000-task projects had p95 ≈ 2.4 s
   while all other endpoints stayed ≈ 110–130 ms p95. The List view is fully paginated and is
   the recommended view for very large projects. Fix: per-column pagination/virtualization.
5. One board per project (by design); no swimlanes, no sub-tasks, no recurring tasks.
6. Comments are plain text (no Markdown, mentions, or editing history beyond "edited").
7. No email verification at registration; registration returns 409 for an existing email,
   which reveals account existence (rate-limited; login/reset do not leak).
8. No notification inbox; assignment notifications are live toasts only.
9. Attachments: no malware scanning; Office documents are accepted based on the ZIP signature
   plus extension. Files live on a local volume (single-host deployment).

## Realtime edge cases

10. Events are published to Redis right after commit (best effort). If Redis is unavailable at
    that instant, *connected* clients miss the live event; they recover on the next board
    refetch (window focus / navigation) or reconnect replay. Readiness turns unhealthy while
    Redis is down.
11. Replay uses the monotonically increasing activity id. Two transactions committing in the
    opposite order of their id allocation could, for a client that disconnects in exactly that
    gap, hide the lower-id event from replay. Snapshots are version-checked and a full resync
    happens on `resync_required`/refetch, so state converges, but that single event could be
    absent from the client's live feed.
12. Presence entries from a crashed API worker linger until their TTL (45 s).

## Security trade-offs

13. `EMAIL_BACKEND=console` (default, so the app works without SMTP) writes password-reset and
    invitation links to the API log. A startup warning is logged in production; configure SMTP
    for real deployments.
14. The per-account lockout (4 × `LOGIN_MAX_FAILURES` within the window) can be triggered by an
    attacker to block logins to a known account for `LOGIN_LOCKOUT_SECONDS`. Per-IP+account
    lockout triggers earlier for the attacker's own IP.
15. Copying a session's cookies to another browser and using both will trigger refresh-token
    reuse detection and sign both out (intended theft protection).

16a. The internal network uses a pinned subnet (`BACKEND_SUBNET`, default `172.30.250.0/24`) so
    the API can restrict which peers may set `X-Forwarded-For`. It can collide with an existing
    network, and two installations on one host need different values (the test scripts use
    `172.30.251–253.0/24`).

## Minor

16. Overdue highlighting on cards uses the browser's local date; server-side overdue counts and
    dashboard day buckets use UTC dates. Around midnight they can differ by one day.
17. Main JS bundle is ~730 kB (≈226 kB gzip); the dashboard (Recharts) is code-split.
18. English-only UI.
