"""Production entrypoint: `python -m forgeboard.serve`.

Runs uvicorn (uvloop + httptools) with N worker processes. Uvicorn's supervisor
handles SIGTERM/SIGINT by draining connections for up to
GRACEFUL_SHUTDOWN_SECONDS before exiting; the app lifespan then closes
WebSockets (code 1012), Redis and the DB pool.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    from forgeboard.config import get_settings
    from forgeboard.logging import configure_logging

    s = get_settings()  # fail fast on invalid/insecure configuration
    configure_logging(s.log_level, json=s.app_env != "development")
    uvicorn.run(
        "forgeboard.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),  # noqa: S104 - container network interface
        port=int(os.environ.get("PORT", "8000")),
        workers=int(os.environ.get("WEB_CONCURRENCY", "2")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "*"),
        timeout_graceful_shutdown=int(os.environ.get("GRACEFUL_SHUTDOWN_SECONDS", "20")),
        timeout_keep_alive=int(os.environ.get("KEEPALIVE_SECONDS", "15")),
        log_config=None,
        access_log=False,
        server_header=False,
        ws_max_size=65536,
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


if __name__ == "__main__":
    main()
