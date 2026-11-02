import { memo, useMemo, useState } from "react";
import {
  closestCorners,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { AlertCircle, CalendarDays, Link2, MessageSquarePlus, Plus } from "lucide-react";
import clsx from "clsx";
import { useAuth } from "@/lib/auth";
import { sortTasks } from "@/lib/board";
import { formatDate, isOverdue } from "@/lib/format";
import { useCreateTask, useMoveTask } from "@/lib/queries";
import { taskTitleSchema } from "@/lib/validation";
import type { Board, Column, PresenceUser, Task } from "@/lib/types";
import { Avatar, EmptyState } from "@/components/ui/Feedback";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { ApiError } from "@/lib/api";
import { useProjectCtx } from "./ProjectLayout";

export const TaskCardBody = memo(function TaskCardBody({
  task,
  projectKey,
  viewers,
}: {
  task: Task;
  projectKey: string;
  viewers?: PresenceUser[];
}) {
  const overdue = isOverdue(task.due_date, task.completed_at);
  return (
    <>
      <div className="task-card-title">{task.title}</div>
      {task.labels.length > 0 && (
        <div className="row row-wrap" style={{ gap: 4 }}>
          {task.labels.map((l) => (
            <span key={l.id} className="label-chip" style={{ ["--chip" as string]: l.color }}>
              {l.name}
            </span>
          ))}
        </div>
      )}
      <div className="task-card-meta">
        <span className="mono">
          {projectKey}-{task.number}
        </span>
        {task.priority !== "none" && <span className={`prio prio-${task.priority}`}>{task.priority}</span>}
        {task.due_date && (
          <span className={clsx("row", overdue && "due-overdue")} style={{ gap: 3 }} title={overdue ? "Overdue" : "Due date"}>
            <CalendarDays size={12} aria-hidden /> {formatDate(task.due_date)}
            {overdue && <span className="sr-only">(overdue)</span>}
          </span>
        )}
        {task.blocked && (
          <span className="blocked-tag row" style={{ gap: 3 }}>
            <Link2 size={12} aria-hidden /> Blocked
          </span>
        )}
        <span className="task-card-viewers row" style={{ gap: 6 }}>
          {viewers && viewers.length > 0 && (
            <span className="faint" title={`${viewers.map((v) => v.display_name).join(", ")} viewing`}>
              <span className="sr-only">Being viewed by {viewers.map((v) => v.display_name).join(", ")}</span>👁
            </span>
          )}
          <span className="avatar-stack">
            {task.assignees.slice(0, 3).map((a) => (
              <Avatar key={a.id} name={a.display_name} size={22} />
            ))}
          </span>
        </span>
      </div>
    </>
  );
});

function SortableCard({
  task,
  projectKey,
  onOpen,
  disabled,
  viewers,
}: {
  task: Task;
  projectKey: string;
  onOpen: (id: string) => void;
  disabled: boolean;
  viewers: PresenceUser[];
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: task.id, disabled });
  return (
    <button
      ref={setNodeRef}
      type="button"
      className={clsx("task-card", isDragging && "task-card-dragging")}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      onClick={() => onOpen(task.id)}
      data-testid="task-card"
      data-task-id={task.id}
      aria-label={`${projectKey}-${task.number} ${task.title}`}
      {...attributes}
      {...listeners}
    >
      <TaskCardBody task={task} projectKey={projectKey} viewers={viewers} />
    </button>
  );
}

function QuickAdd({ projectId, column }: { projectId: string; column: Column }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string>();
  const create = useCreateTask(projectId);
  const { toast } = useToast();
  if (!open)
    return (
      <div className="quick-add">
        <Button variant="ghost" size="sm" onClick={() => setOpen(true)} style={{ width: "100%", justifyContent: "flex-start" }} aria-label={`Add task to ${column.name}`}>
          <Plus size={15} /> Add task
        </Button>
      </div>
    );
  return (
    <form
      className="quick-add stack"
      style={{ gap: 6 }}
      onSubmit={async (e) => {
        e.preventDefault();
        const parsed = taskTitleSchema.safeParse(title);
        if (!parsed.success) return setError(parsed.error.issues[0].message);
        setError(undefined);
        try {
          await create.mutateAsync({ title: parsed.data, column_id: column.id });
          setTitle("");
        } catch (err) {
          toast({ title: "Could not create task", description: err instanceof ApiError ? err.message : undefined, variant: "error" });
        }
      }}
    >
      <label className="sr-only" htmlFor={`qa-${column.id}`}>
        New task title in {column.name}
      </label>
      <input
        id={`qa-${column.id}`}
        className="input"
        autoFocus
        placeholder="Task title"
        value={title}
        maxLength={200}
        aria-invalid={error ? true : undefined}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      />
      {error && <p className="field-error" role="alert">{error}</p>}
      <div className="row">
        <Button type="submit" size="sm" variant="primary" loading={create.isPending}>
          Add
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function ColumnView({
  column,
  taskIds,
  tasks,
  board,
  onOpen,
  dragDisabled,
  viewersByTask,
}: {
  column: Column;
  taskIds: string[];
  tasks: Map<string, Task>;
  board: Board;
  onOpen: (id: string) => void;
  dragDisabled: boolean;
  viewersByTask: Map<string, PresenceUser[]>;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `col:${column.id}` });
  const over = column.wip_limit !== null && taskIds.length > column.wip_limit;
  return (
    <section className={clsx("column", isOver && "column-over")} aria-label={`${column.name} column`} data-testid="column" data-column-name={column.name}>
      <header className="column-header">
        <h2 style={{ fontSize: 14 }}>{column.name}</h2>
        <span className={clsx("column-count", over && "column-count-over")} title={column.wip_limit ? `WIP limit ${column.wip_limit}` : undefined}>
          {taskIds.length}
          {column.wip_limit ? ` / ${column.wip_limit}` : ""}
        </span>
        {column.is_done && <span className="badge badge-success">done</span>}
      </header>
      <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
        <div ref={setNodeRef} className="column-body">
          {taskIds.map((id) => {
            const t = tasks.get(id);
            return t ? (
              <SortableCard
                key={id}
                task={t}
                projectKey={board.project.key}
                onOpen={onOpen}
                disabled={dragDisabled}
                viewers={viewersByTask.get(id) ?? []}
              />
            ) : null;
          })}
          {taskIds.length === 0 && <p className="faint" style={{ padding: "12px 4px", fontSize: 13 }}>No tasks</p>}
        </div>
      </SortableContext>
      {board.can_edit && <QuickAdd projectId={board.project.id} column={column} />}
    </section>
  );
}

export function BoardPage() {
  const { board, openTask, presence } = useProjectCtx();
  const { user } = useAuth();
  const move = useMoveTask(board.project.id);
  const { toast } = useToast();
  const [filter, setFilter] = useState("");
  const [mine, setMine] = useState(false);
  const [containers, setContainers] = useState<Record<string, string[]> | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 220, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const taskMap = useMemo(() => new Map(board.tasks.map((t) => [t.id, t])), [board.tasks]);
  const filtering = filter.trim() !== "" || mine;
  const base = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const out: Record<string, string[]> = {};
    for (const c of board.columns) out[c.id] = [];
    for (const t of sortTasks(board.tasks)) {
      if (q && !t.title.toLowerCase().includes(q) && !`${board.project.key}-${t.number}`.toLowerCase().includes(q)) continue;
      if (mine && !t.assignees.some((a) => a.id === user?.id)) continue;
      out[t.column_id]?.push(t.id);
    }
    return out;
  }, [board, filter, mine, user?.id]);
  const items = containers ?? base;

  const viewersByTask = useMemo(() => {
    const m = new Map<string, PresenceUser[]>();
    for (const p of presence) {
      if (p.user_id === user?.id) continue;
      for (const tid of p.viewing_task_ids) m.set(tid, [...(m.get(tid) ?? []), p]);
    }
    return m;
  }, [presence, user?.id]);

  const findContainer = (id: string, state: Record<string, string[]>) => {
    if (id.startsWith("col:")) return id.slice(4);
    return Object.keys(state).find((c) => state[c].includes(id));
  };

  const onDragStart = (e: DragStartEvent) => {
    setActiveId(String(e.active.id));
    setContainers(base);
  };

  const onDragOver = ({ active, over }: DragOverEvent) => {
    if (!over || !containers) return;
    const from = findContainer(String(active.id), containers);
    const to = findContainer(String(over.id), containers);
    if (!from || !to || from === to) return;
    setContainers((prev) => {
      if (!prev) return prev;
      const source = prev[from].filter((x) => x !== active.id);
      const target = [...prev[to]];
      const overIndex = target.indexOf(String(over.id));
      target.splice(overIndex >= 0 ? overIndex : target.length, 0, String(active.id));
      return { ...prev, [from]: source, [to]: target };
    });
  };

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    const state = containers;
    setContainers(null);
    setActiveId(null);
    if (!over || !state) return;
    const id = String(active.id);
    const to = findContainer(String(over.id), state);
    if (!to) return;
    let list = state[to];
    const oldIndex = list.indexOf(id);
    const overIndex = String(over.id).startsWith("col:") ? list.length - 1 : list.indexOf(String(over.id));
    if (oldIndex >= 0 && overIndex >= 0 && oldIndex !== overIndex) list = arrayMove(list, oldIndex, overIndex);
    const index = list.indexOf(id);
    const task = taskMap.get(id);
    if (!task) return;
    const originalIndex = base[task.column_id]?.indexOf(id);
    if (task.column_id === to && originalIndex === index) return;
    const target = board.columns.find((c) => c.id === to);
    if (target && target.id !== task.column_id && target.wip_limit !== null && (base[to]?.length ?? 0) >= target.wip_limit) {
      toast({ title: "WIP limit reached", description: `${target.name} allows at most ${target.wip_limit} tasks.`, variant: "warning" });
      return;
    }
    move.mutate(
      { task, columnId: to, index },
      {
        onError: (err) => {
          const conflict = err instanceof ApiError && err.isConflict;
          toast({
            title: conflict ? "Task changed by someone else" : "Move failed",
            description: conflict ? "The board was refreshed with the latest version." : err instanceof ApiError ? err.message : undefined,
            variant: conflict ? "warning" : "error",
          });
        },
      },
    );
  };

  const active = activeId ? taskMap.get(activeId) : undefined;

  return (
    <>
      <div className="board-toolbar">
        <label className="sr-only" htmlFor="board-filter">
          Filter tasks
        </label>
        <input
          id="board-filter"
          className="input"
          style={{ maxWidth: 260 }}
          placeholder="Filter by title or key…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <label className="checkbox-row">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Only my tasks
        </label>
        <span className="spacer" />
        {filtering && board.can_edit && (
          <span className="muted row" style={{ fontSize: 12 }}>
            <AlertCircle size={14} /> Drag & drop is paused while filtering
          </span>
        )}
        {!board.can_edit && <span className="badge">Read-only</span>}
      </div>
      {board.tasks.length === 0 && !board.can_edit ? (
        <EmptyState icon={<MessageSquarePlus size={28} />} title="No tasks yet">
          This project doesn't have any tasks.
        </EmptyState>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={onDragStart}
          onDragOver={onDragOver}
          onDragEnd={onDragEnd}
          onDragCancel={() => {
            setContainers(null);
            setActiveId(null);
          }}
        >
          <div className="board" data-testid="board">
            {board.columns.map((c) => (
              <ColumnView
                key={c.id}
                column={c}
                taskIds={items[c.id] ?? []}
                tasks={taskMap}
                board={board}
                onOpen={openTask}
                dragDisabled={!board.can_edit || filtering}
                viewersByTask={viewersByTask}
              />
            ))}
          </div>
          <DragOverlay>
            {active ? (
              <div className="task-card task-card-overlay">
                <TaskCardBody task={active} projectKey={board.project.key} />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      )}
    </>
  );
}
