import { useEffect, useRef, useState } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { realtime, type ConnectionStatus, type ServerEvent } from "./realtime";
import { removeTask, upsertColumn, upsertTask } from "./board";
import { qk } from "./queries";
import type { Board, Column, PresenceUser, Task } from "./types";

export interface RealtimeCallbacks {
  onRevoked?: () => void;
  onDeleted?: () => void;
  onEvent?: (e: ServerEvent) => void;
}

/** Apply a server event to the cached board; returns true if fully handled locally. */
export function applyEventToCache(qc: QueryClient, projectId: string, ev: ServerEvent): void {
  const p = ev.payload ?? {};
  const setBoard = (fn: (b: Board) => Board) => qc.setQueryData<Board>(qk.board(projectId), (b) => (b ? fn(b) : b));
  const bumpLast = (b: Board) => (ev.id > b.last_event_id ? { ...b, last_event_id: ev.id } : b);

  switch (ev.type) {
    case "task.created":
    case "task.updated":
    case "task.assigned":
    case "task.moved":
    case "dependency.added":
    case "dependency.removed": {
      const task = p.task as Task;
      setBoard((b) => bumpLast(upsertTask(b, task)));
      qc.invalidateQueries({ queryKey: qk.task(task.id) });
      qc.invalidateQueries({ queryKey: qk.history(task.id) });
      break;
    }
    case "task.deleted":
      setBoard((b) => bumpLast(removeTask(b, p.task.id)));
      qc.invalidateQueries({ queryKey: qk.task(p.task.id) });
      break;
    case "comment.created":
    case "comment.updated":
    case "comment.deleted":
    case "attachment.added":
    case "attachment.deleted":
      if (ev.task_id) qc.invalidateQueries({ queryKey: qk.task(ev.task_id) });
      setBoard(bumpLast);
      break;
    case "column.created":
    case "column.updated":
      setBoard((b) => bumpLast(upsertColumn(b, p.column as Column)));
      if (p.done_changed) qc.invalidateQueries({ queryKey: qk.board(projectId) });
      break;
    case "column.reordered":
      setBoard((b) => bumpLast({ ...b, columns: p.columns as Column[] }));
      break;
    default:
      // project.*, label.*, column.deleted/rebalanced, membership changes: refetch authoritative state
      qc.invalidateQueries({ queryKey: qk.board(projectId) });
  }
  qc.invalidateQueries({ queryKey: qk.activity(projectId) });
  qc.invalidateQueries({ queryKey: ["tasks", projectId] });
  qc.invalidateQueries({ queryKey: qk.graph(projectId) });
}

export function useConnectionStatus(): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>(realtime.status);
  useEffect(() => realtime.onStatus(setStatus), []);
  return status;
}

/** Subscribe the current view to a project's realtime stream. */
export function useProjectRealtime(projectId: string, lastEventId: number | undefined, cb: RealtimeCallbacks = {}) {
  const qc = useQueryClient();
  const [presence, setPresence] = useState<PresenceUser[]>([]);
  const cbRef = useRef(cb);
  cbRef.current = cb;
  const ready = lastEventId !== undefined;

  useEffect(() => {
    if (!ready) return;
    const unsub = realtime.subscribe(projectId, lastEventId ?? 0, (msg) => {
      switch (msg.kind) {
        case "event":
          applyEventToCache(qc, projectId, msg.event);
          cbRef.current.onEvent?.(msg.event);
          break;
        case "presence":
          setPresence(msg.users);
          break;
        case "resync":
          qc.invalidateQueries({ queryKey: qk.board(projectId) });
          break;
        case "revoked":
          cbRef.current.onRevoked?.();
          break;
        case "deleted":
          cbRef.current.onDeleted?.();
          break;
        default:
          break;
      }
    });
    return () => {
      unsub();
      setPresence([]);
    };
    // Subscribe once per project; later board refetches must not resubscribe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, ready, qc]);

  return { presence };
}
