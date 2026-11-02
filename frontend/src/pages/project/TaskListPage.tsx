import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate, isOverdue, PRIORITY_LABEL, relativeTime } from "@/lib/format";
import type { Page, Task } from "@/lib/types";
import { SelectField, TextField } from "@/components/ui/Field";
import { Avatar, Badge, EmptyState, ErrorState, LoadingState } from "@/components/ui/Feedback";
import { Button } from "@/components/ui/Button";
import { useProjectCtx } from "./ProjectLayout";

type SortKey = "number" | "title" | "priority" | "due_date" | "updated_at" | "created_at";

function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function TaskListPage() {
  const { board, projectId, openTask } = useProjectCtx();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const debouncedQ = useDebounced(q);
  const status = params.get("status") ?? "";
  const priority = params.get("priority") ?? "";
  const assignee = params.get("assignee") ?? "";
  const special = params.get("special") ?? "";
  const sort = (params.get("sort") as SortKey) ?? "updated_at";
  const direction = (params.get("dir") as "asc" | "desc") ?? "desc";

  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  useEffect(() => setParam("q", debouncedQ), [debouncedQ]); // eslint-disable-line react-hooks/exhaustive-deps

  const filters = {
    q: debouncedQ || undefined,
    status: status || undefined,
    priority: priority ? [priority] : undefined,
    assignee: assignee && assignee !== "none" ? [assignee] : undefined,
    unassigned: assignee === "none" || undefined,
    overdue: special === "overdue" || undefined,
    dependency_state: special === "blocked" || special === "ready" ? special : undefined,
    sort,
    direction,
    limit: 50,
    include_total: true,
  };

  const query = useInfiniteQuery({
    queryKey: ["tasks", projectId, filters],
    queryFn: ({ pageParam, signal }) =>
      api.get<Page<Task>>(`/projects/${projectId}/tasks`, { ...filters, cursor: pageParam ?? undefined } as never, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });

  const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;
  const colName = new Map(board.columns.map((c) => [c.id, c.name]));

  const sortHeader = (key: SortKey, label: string) => {
    const active = sort === key;
    return (
      <th aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
        <button
          className="th-sort"
          onClick={() => {
            const next = new URLSearchParams(params);
            next.set("sort", key);
            next.set("dir", active && direction === "desc" ? "asc" : active ? "desc" : key === "title" || key === "number" || key === "due_date" ? "asc" : "desc");
            setParams(next, { replace: true });
          }}
        >
          {label}
          {active && (direction === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
        </button>
      </th>
    );
  };

  return (
    <>
      <div className="filters">
        <TextField label="Search" placeholder="Search title, description or key (e.g. KEY-12)" value={q} onChange={(e) => setQ(e.target.value)} type="search" />
        <SelectField label="Status" value={status} onChange={(e) => setParam("status", e.target.value)}>
          <option value="">Any status</option>
          <option value="open">Open</option>
          <option value="done">Done</option>
        </SelectField>
        <SelectField label="Priority" value={priority} onChange={(e) => setParam("priority", e.target.value)}>
          <option value="">Any priority</option>
          {Object.entries(PRIORITY_LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </SelectField>
        <SelectField label="Assignee" value={assignee} onChange={(e) => setParam("assignee", e.target.value)}>
          <option value="">Anyone</option>
          <option value="none">Unassigned</option>
          {board.members.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
            </option>
          ))}
        </SelectField>
        <SelectField label="Show" value={special} onChange={(e) => setParam("special", e.target.value)}>
          <option value="">All tasks</option>
          <option value="overdue">Overdue</option>
          <option value="blocked">Blocked</option>
          <option value="ready">Ready to start</option>
        </SelectField>
      </div>
      {query.isLoading ? (
        <LoadingState />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title="No matching tasks">Try adjusting your search or filters.</EmptyState>
      ) : (
        <div className="card">
          <div className="card-header">
            <span className="muted" role="status" aria-live="polite">
              {total} task{total === 1 ? "" : "s"}
              {query.isFetching && !query.isFetchingNextPage ? " · updating…" : ""}
            </span>
          </div>
          <div className="table-wrap">
            <table className="table" data-testid="task-table">
              <thead>
                <tr>
                  {sortHeader("number", "Key")}
                  {sortHeader("title", "Title")}
                  <th>Status</th>
                  {sortHeader("priority", "Priority")}
                  {sortHeader("due_date", "Due")}
                  <th>Assignees</th>
                  {sortHeader("updated_at", "Updated")}
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id}>
                    <td className="mono">
                      {board.project.key}-{t.number}
                    </td>
                    <td className="title-cell">
                      <button className="th-sort" style={{ fontWeight: 550 }} onClick={() => openTask(t.id)}>
                        {t.title}
                      </button>{" "}
                      {t.blocked && <Badge tone="warning">blocked</Badge>}
                    </td>
                    <td>{colName.get(t.column_id)}</td>
                    <td>
                      <span className={`prio prio-${t.priority}`}>{PRIORITY_LABEL[t.priority]}</span>
                    </td>
                    <td className={isOverdue(t.due_date, t.completed_at) ? "due-overdue" : undefined}>{formatDate(t.due_date)}</td>
                    <td>
                      <span className="avatar-stack">
                        {t.assignees.map((a) => (
                          <Avatar key={a.id} name={a.display_name} size={22} />
                        ))}
                      </span>
                    </td>
                    <td className="muted">{relativeTime(t.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {query.hasNextPage && (
            <div style={{ padding: 12, textAlign: "center" }}>
              <Button onClick={() => query.fetchNextPage()} loading={query.isFetchingNextPage}>
                Load more
              </Button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
