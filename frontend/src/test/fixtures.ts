import type { Board, Column, Task } from "@/lib/types";

export function col(id: string, position: number, is_done = false): Column {
  return { id, project_id: "p", name: id, position, wip_limit: null, is_done };
}

export function task(id: string, column_id: string, position: number, extra: Partial<Task> = {}): Task {
  return {
    id,
    project_id: "p",
    column_id,
    number: 1,
    title: id,
    description: "",
    priority: "none",
    due_date: null,
    position,
    version: 1,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    assignees: [],
    labels: [],
    blocked: false,
    dependency_ids: [],
    ...extra,
  };
}

export function board(tasks: Task[], columns = [col("todo", 1), col("doing", 2), col("done", 3, true)]): Board {
  return {
    project: { id: "p", org_id: "o", name: "P", key: "P", description: "", status: "active", version: 1, created_at: "", updated_at: "", archived_at: null },
    columns,
    labels: [],
    members: [],
    tasks,
    last_event_id: 0,
    can_edit: true,
    role: "member",
  };
}
