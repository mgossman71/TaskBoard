"""Task dependency graph algorithms (pure, no I/O).

Edge convention: (task, depends_on) means `task` cannot start until `depends_on`
is done. All algorithms are O(V + E) (topological order: O((V + E) log V) due to
deterministic heap-based tie-breaking), so projects with thousands of tasks and
tens of thousands of edges are handled in milliseconds.
"""

from __future__ import annotations

import heapq
from collections import defaultdict, deque
from collections.abc import Callable, Hashable, Iterable
from typing import Any, TypeVar

N = TypeVar("N", bound=Hashable)


class CycleError(ValueError):
    def __init__(self, cycle: list[Any]):
        super().__init__("dependency cycle detected")
        self.cycle = cycle


def _adjacency(edges: Iterable[tuple[N, N]]) -> dict[N, list[N]]:
    adj: dict[N, list[N]] = defaultdict(list)
    for task, dep in edges:
        adj[task].append(dep)
    return adj


def find_path(edges: Iterable[tuple[N, N]], start: N, goal: N) -> list[N] | None:
    """Shortest path start -> ... -> goal following depends-on edges, or None."""
    if start == goal:
        return [start]
    adj = _adjacency(edges)
    parent: dict[N, N | None] = {start: None}
    q: deque[N] = deque([start])
    while q:
        node = q.popleft()
        for nxt in adj.get(node, ()):
            if nxt in parent:
                continue
            parent[nxt] = node
            if nxt == goal:
                path = [nxt]
                cur: N | None = node
                while cur is not None:
                    path.append(cur)
                    cur = parent[cur]
                return list(reversed(path))
            q.append(nxt)
    return None


def cycle_if_added(edges: Iterable[tuple[N, N]], task: N, depends_on: N) -> list[N] | None:
    """If adding (task -> depends_on) would create a cycle, return the cycle
    [task, depends_on, ..., task]; otherwise None."""
    if task == depends_on:
        return [task, task]
    path = find_path(edges, depends_on, task)
    if path is None:
        return None
    return [task, *path]


def topological_order(
    nodes: Iterable[N], edges: Iterable[tuple[N, N]], key: Callable[[N], Any] | None = None
) -> list[N]:
    """Kahn's algorithm: dependencies appear before dependents. Ties are broken by
    `key` (smallest first) for deterministic output. Raises CycleError on cycles."""
    node_list = list(nodes)
    node_set = set(node_list)
    dependents: dict[N, list[N]] = defaultdict(list)
    indeg: dict[N, int] = dict.fromkeys(node_list, 0)
    edge_list = [(t, d) for t, d in edges if t in node_set and d in node_set]
    for task, dep in edge_list:
        dependents[dep].append(task)
        indeg[task] += 1
    keyf = key or (lambda n: n)
    counter = 0
    heap: list[tuple[Any, int, N]] = []
    for n in node_list:
        if indeg[n] == 0:
            heap.append((keyf(n), counter, n))
            counter += 1
    heapq.heapify(heap)
    order: list[N] = []
    while heap:
        _, _, n = heapq.heappop(heap)
        order.append(n)
        for m in dependents.get(n, ()):
            indeg[m] -= 1
            if indeg[m] == 0:
                heapq.heappush(heap, (keyf(m), counter, m))
                counter += 1
    if len(order) != len(node_list):
        remaining = {n for n in node_list if indeg[n] > 0}
        raise CycleError(_extract_cycle(remaining, edge_list))
    return order


def _extract_cycle(remaining: set[N], edges: list[tuple[N, N]]) -> list[N]:
    adj = _adjacency((t, d) for t, d in edges if t in remaining and d in remaining)
    start = next(iter(remaining))
    seen: dict[N, int] = {}
    path: list[N] = []
    node = start
    while node not in seen:
        seen[node] = len(path)
        path.append(node)
        node = adj[node][0]
    return [*path[seen[node] :], node]


def blocked_and_ready(nodes: Iterable[N], edges: Iterable[tuple[N, N]], done: set[N]) -> tuple[set[N], set[N]]:
    """blocked: not done and at least one dependency not done.
    ready: not done and every dependency done (including tasks without dependencies)."""
    node_list = list(nodes)
    has_open_dep: set[N] = set()
    for task, dep in edges:
        if dep not in done:
            has_open_dep.add(task)
    blocked = {n for n in node_list if n not in done and n in has_open_dep}
    ready = {n for n in node_list if n not in done and n not in has_open_dep}
    return blocked, ready
