"""Operational CLI.

    python -m forgeboard.cli seed-load --users 100 --tasks 10000 --out /tmp/seed.json
        Bulk-creates a *load-test* organization (explicit command only; never run
        automatically) and writes credentials/ids for the k6 scenario.
    python -m forgeboard.cli cleanup-orphans
        Removes attachment files that have no database row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import insert

from forgeboard.db import get_sessionmaker
from forgeboard.models import BoardColumn, Membership, Organization, Project, ProjectMember, Role, Task, TaskDependency, User, task_assignees
from forgeboard.security.passwords import hash_password

DEFAULT_COLUMNS = [("To Do", False), ("In Progress", False), ("In Review", False), ("Done", True)]
WORDS = "api auth billing cache dashboard deploy docs export import invoice login metrics migration mobile onboarding payments search settings sync upload".split()


async def seed_load(users: int, tasks: int, projects: int, password: str, out: str) -> None:
    rng = random.Random(1234)
    pw_hash = hash_password(password)  # one hash for all synthetic users (speed)
    tag = uuid.uuid4().hex[:6]
    now = datetime.now(UTC)
    async with get_sessionmaker()() as s:
        org = Organization(name=f"Load Test {tag}", slug=f"load-{tag}")
        s.add(org)
        await s.flush()
        user_rows = [
            {"id": uuid.uuid4(), "email": f"load{i}-{tag}@example.com", "display_name": f"Load User {i}", "password_hash": pw_hash}
            for i in range(users)
        ]
        await s.execute(insert(User), user_rows)
        await s.execute(
            insert(Membership),
            [{"org_id": org.id, "user_id": u["id"], "role": Role.OWNER if i == 0 else Role.MEMBER} for i, u in enumerate(user_rows)],
        )
        proj_ids, done_cols, open_cols = [], {}, {}
        per_project = tasks // projects
        for p in range(projects):
            pid = uuid.uuid4()
            proj_ids.append(pid)
            await s.execute(
                insert(Project), [{"id": pid, "org_id": org.id, "name": f"Load Project {p}", "key": f"LP{p}", "task_seq": per_project}]
            )
            cols = []
            for i, (name, done) in enumerate(DEFAULT_COLUMNS):
                cid = uuid.uuid4()
                cols.append((cid, done))
                await s.execute(insert(BoardColumn), [{"id": cid, "project_id": pid, "name": name, "position": (i + 1) * 1024.0, "is_done": done}])
            done_cols[pid] = [c for c, d in cols if d]
            open_cols[pid] = [c for c, d in cols if not d]
            await s.execute(insert(ProjectMember), [{"project_id": pid, "user_id": u["id"]} for u in user_rows])
            task_rows, assign_rows, dep_rows = [], [], []
            for n in range(per_project):
                tid = uuid.uuid4()
                done = rng.random() < 0.3
                col = done_cols[pid][0] if done else rng.choice(open_cols[pid])
                created = now - timedelta(days=rng.randint(0, 60), minutes=rng.randint(0, 1440))
                task_rows.append(
                    {
                        "id": tid,
                        "project_id": pid,
                        "column_id": col,
                        "number": n + 1,
                        "title": f"{rng.choice(WORDS).title()} {rng.choice(WORDS)} task {n + 1}",
                        "description": " ".join(rng.choices(WORDS, k=12)),
                        "priority": rng.choice(["none", "low", "medium", "high", "urgent"]),
                        "due_date": (date.today() + timedelta(days=rng.randint(-20, 40))) if rng.random() < 0.6 else None,
                        "position": float(n + 1) * 1024.0,
                        "created_at": created,
                        "updated_at": created,
                        "completed_at": created + timedelta(days=1) if done else None,
                    }
                )
                assign_rows.append({"task_id": tid, "user_id": rng.choice(user_rows)["id"]})
                if n > 0 and rng.random() < 0.4:
                    dep_rows.append({"task_id": tid, "depends_on_id": task_rows[rng.randrange(max(0, n - 50), n)]["id"], "project_id": pid})
            for i in range(0, len(task_rows), 1000):
                await s.execute(insert(Task), task_rows[i : i + 1000])
            for i in range(0, len(assign_rows), 2000):
                await s.execute(insert(task_assignees), assign_rows[i : i + 2000])
            uniq = list({(d["task_id"], d["depends_on_id"]): d for d in dep_rows}.values())
            for i in range(0, len(uniq), 2000):
                await s.execute(insert(TaskDependency), uniq[i : i + 2000])
        await s.commit()
    data = {
        "org_id": str(org.id),
        "project_ids": [str(p) for p in proj_ids],
        "password": password,
        "emails": [u["email"] for u in user_rows],
        "tasks": tasks,
    }
    with open(out, "w") as fh:
        json.dump(data, fh)
    print(f"seeded org {org.id}: {users} users, {projects} projects, {per_project * projects} tasks -> {out}")


async def cleanup_orphans() -> None:
    from forgeboard.services.attachments import sweep_orphans

    async with get_sessionmaker()() as s:
        print(f"removed {await sweep_orphans(s)} orphaned files")


def main() -> None:
    parser = argparse.ArgumentParser(prog="forgeboard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sl = sub.add_parser("seed-load", help="create a synthetic load-test organization")
    sl.add_argument("--users", type=int, default=100)
    sl.add_argument("--tasks", type=int, default=10_000)
    sl.add_argument("--projects", type=int, default=5)
    sl.add_argument("--password", default="Load-Test-Passw0rd!")
    sl.add_argument("--out", default="/tmp/seed.json")
    sub.add_parser("cleanup-orphans", help="delete attachment files without DB rows")
    args = parser.parse_args()
    if args.cmd == "seed-load":
        asyncio.run(seed_load(args.users, args.tasks, args.projects, args.password, args.out))
    else:
        asyncio.run(cleanup_orphans())


if __name__ == "__main__":
    main()
