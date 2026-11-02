/**
 * Pure board-state helpers shared by optimistic updates and realtime events.
 */
import type { Board, Column, Task } from "./types";

export function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => a.position - b.position || a.id.localeCompare(b.id));
}

export function tasksByColumn(board: Board): Record<string, Task[]> {
  const out: Record<string, Task[]> = {};
  for (const c of board.columns) out[c.id] = [];
  for (const t of sortTasks(board.tasks)) (out[t.column_id] ??= []).push(t);
  return out;
}

/** Recompute `blocked` for every task from dependency_ids + done columns. */
export function withBlocked(board: Board): Board {
  const done = new Set(board.columns.filter((c) => c.is_done).map((c) => c.id));
  const colOf = new Map(board.tasks.map((t) => [t.id, t.column_id]));
  let changed = false;
  const tasks = board.tasks.map((t) => {
    const blocked = t.dependency_ids.some((d) => {
      const col = colOf.get(d);
      return col !== undefined && !done.has(col);
    });
    if (blocked !== t.blocked) {
      changed = true;
      return { ...t, blocked };
    }
    return t;
  });
  return changed ? { ...board, tasks } : board;
}

/** Insert or replace a task, ignoring stale snapshots (lower version). */
export function upsertTask(board: Board, task: Task): Board {
  const idx = board.tasks.findIndex((t) => t.id === task.id);
  if (idx >= 0 && board.tasks[idx].version > task.version) return board;
  const tasks = idx >= 0 ? board.tasks.map((t, i) => (i === idx ? task : t)) : [...board.tasks, task];
  return withBlocked({ ...board, tasks });
}

export function removeTask(board: Board, taskId: string): Board {
  const tasks = board.tasks
    .filter((t) => t.id !== taskId)
    .map((t) => (t.dependency_ids.includes(taskId) ? { ...t, dependency_ids: t.dependency_ids.filter((d) => d !== taskId) } : t));
  return withBlocked({ ...board, tasks });
}

export function upsertColumn(board: Board, col: Column): Board {
  const exists = board.columns.some((c) => c.id === col.id);
  const columns = (exists ? board.columns.map((c) => (c.id === col.id ? col : c)) : [...board.columns, col]).sort(
    (a, b) => a.position - b.position,
  );
  return withBlocked({ ...board, columns });
}

/**
 * Compute neighbour ids and an optimistic position for dropping `taskId` at
 * `index` within `columnId` (index counted without the moving task).
 */
export function dropTarget(
  board: Board,
  taskId: string,
  columnId: string,
  index: number,
): { after_id: string | null; before_id: string | null; position: number } {
  const col = sortTasks(board.tasks.filter((t) => t.column_id === columnId && t.id !== taskId));
  const i = Math.max(0, Math.min(index, col.length));
  const prev = col[i - 1] ?? null;
  const next = col[i] ?? null;
  let position: number;
  if (prev && next) position = (prev.position + next.position) / 2;
  else if (prev) position = prev.position + 1024;
  else if (next) position = next.position - 1024;
  else position = 1024;
  return { after_id: prev?.id ?? null, before_id: prev ? null : (next?.id ?? null), position };
}

export function moveTaskLocally(board: Board, taskId: string, columnId: string, position: number): Board {
  const col = board.columns.find((c) => c.id === columnId);
  const tasks = board.tasks.map((t) => {
    if (t.id !== taskId) return t;
    const wasDone = board.columns.find((c) => c.id === t.column_id)?.is_done;
    let completed_at = t.completed_at;
    if (col?.is_done && !wasDone) completed_at = new Date().toISOString();
    if (!col?.is_done) completed_at = null;
    return { ...t, column_id: columnId, position, completed_at };
  });
  return withBlocked({ ...board, tasks });
}
