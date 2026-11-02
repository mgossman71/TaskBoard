import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Link2, Paperclip, Trash2, X } from "lucide-react";
import { api, ApiError, downloadAttachment } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { describeActivity } from "@/lib/activity";
import { formatBytes, formatDateTime, isOverdue, PRIORITY_LABEL, relativeTime } from "@/lib/format";
import { applyTaskSnapshot, qk, useDeleteTask, useMoveTask, useTaskDetail, useTaskHistory, useUpdateTask, type TaskPatch } from "@/lib/queries";
import { sortTasks } from "@/lib/board";
import { taskTitleSchema } from "@/lib/validation";
import type { Board, Comment, PresenceUser, Task, TaskDetail, TaskRef } from "@/lib/types";
import { Modal, useConfirm } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { SelectField, TextAreaField, TextField } from "@/components/ui/Field";
import { Avatar, Badge, ErrorState, LoadingState, Spinner } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toast";

interface ConflictState {
  patch: Omit<TaskPatch, "version">;
  current: Task;
}

function ConflictBanner({ conflict, onReload, onOverwrite, busy }: { conflict: ConflictState; onReload: () => void; onOverwrite: () => void; busy: boolean }) {
  return (
    <div className="form-error stack" role="alert" style={{ gap: 8 }} data-testid="conflict-banner">
      <strong>This task was changed by someone else while you were editing.</strong>
      <span>
        Latest version: “{conflict.current.title}” (v{conflict.current.version}). Your change: {Object.keys(conflict.patch).join(", ")}.
      </span>
      <div className="row row-wrap">
        <Button size="sm" onClick={onReload}>
          Discard mine, use latest
        </Button>
        <Button size="sm" variant="danger" onClick={onOverwrite} loading={busy}>
          Overwrite with my changes
        </Button>
      </div>
    </div>
  );
}

function Comments({ task, canWrite, isAdmin }: { task: TaskDetail; canWrite: boolean; isAdmin: boolean }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const { error: toastError } = useToast();
  const [body, setBody] = useState("");
  const [err, setErr] = useState<string>();
  const add = useMutation({
    mutationFn: (b: string) => api.post<Comment>(`/tasks/${task.id}/comments`, { body: b }),
    onMutate: async (b) => {
      // optimistic append
      const prev = qc.getQueryData<TaskDetail>(qk.task(task.id));
      if (prev && user)
        qc.setQueryData<TaskDetail>(qk.task(task.id), {
          ...prev,
          comments: [
            ...prev.comments,
            { id: `tmp-${Date.now()}`, task_id: task.id, author: { id: user.id, display_name: user.display_name, email: user.email }, body: b, created_at: new Date().toISOString(), edited_at: null },
          ],
        });
      return { prev };
    },
    onError: (e, _b, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.task(task.id), ctx.prev);
      toastError(e, "Comment not saved");
    },
    onSettled: () => qc.invalidateQueries({ queryKey: qk.task(task.id) }),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/comments/${id}`),
    onSettled: () => qc.invalidateQueries({ queryKey: qk.task(task.id) }),
    onError: (e) => toastError(e, "Could not delete comment"),
  });
  return (
    <section aria-labelledby="comments-h" className="stack">
      <h3 id="comments-h" className="section-title">
        Comments ({task.comments.length})
      </h3>
      {task.comments.map((c) => (
        <div key={c.id} className="comment" data-testid="comment">
          <Avatar name={c.author?.display_name ?? "Deleted user"} size={28} />
          <div className="comment-body">
            <div className="row" style={{ fontSize: 12 }}>
              <strong>{c.author?.display_name ?? "Deleted user"}</strong>
              <span className="faint" title={formatDateTime(c.created_at)}>
                {relativeTime(c.created_at)}
                {c.edited_at && " (edited)"}
              </span>
              <span className="spacer" />
              {canWrite && (c.author?.id === user?.id || isAdmin) && !c.id.startsWith("tmp-") && (
                <Button size="sm" variant="ghost" iconOnly aria-label="Delete comment" onClick={() => del.mutate(c.id)}>
                  <X size={14} />
                </Button>
              )}
            </div>
            <p className="comment-text">{c.body}</p>
          </div>
        </div>
      ))}
      {canWrite && (
        <form
          className="stack"
          style={{ gap: 6 }}
          onSubmit={(e) => {
            e.preventDefault();
            const v = body.trim();
            if (!v) return setErr("Comment cannot be empty");
            if (v.length > 10000) return setErr("Comment is too long");
            setErr(undefined);
            add.mutate(v);
            setBody("");
          }}
        >
          <TextAreaField label="Add a comment" hideLabel placeholder="Write a comment…" value={body} onChange={(e) => setBody(e.target.value)} error={err} rows={3} />
          <div>
            <Button type="submit" size="sm" variant="primary" loading={add.isPending}>
              Comment
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}

function Attachments({ task, canWrite, isAdmin }: { task: TaskDetail; canWrite: boolean; isAdmin: boolean }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const { toast, error: toastError } = useToast();
  const confirm = useConfirm();
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post(`/tasks/${task.id}/attachments`, fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.task(task.id) });
      toast({ title: "File attached", variant: "success" });
    },
    onError: (e) => toastError(e, "Upload failed"),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/attachments/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.task(task.id) }),
    onError: (e) => toastError(e, "Could not delete attachment"),
  });
  return (
    <section aria-labelledby="att-h" className="stack" style={{ gap: 8 }}>
      <div className="row">
        <h3 id="att-h" className="section-title" style={{ margin: 0 }}>
          Attachments ({task.attachments.length})
        </h3>
        <span className="spacer" />
        {canWrite && (
          <>
            <input
              ref={input}
              type="file"
              className="sr-only"
              id={`file-${task.id}`}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
            <Button size="sm" onClick={() => input.current?.click()} loading={upload.isPending}>
              <Paperclip size={14} /> Attach file
            </Button>
          </>
        )}
      </div>
      {task.attachments.length === 0 && <p className="faint">No attachments.</p>}
      {task.attachments.map((a) => (
        <div key={a.id} className="file-row">
          <Paperclip size={14} aria-hidden />
          <span className="name" title={a.filename}>
            {a.filename}
          </span>
          <span className="faint" style={{ fontSize: 12 }}>
            {formatBytes(a.size_bytes)}
          </span>
          <Button size="sm" variant="ghost" iconOnly aria-label={`Download ${a.filename}`} onClick={() => downloadAttachment(a.id, a.filename).catch((e) => toastError(e, "Download failed"))}>
            <Download size={14} />
          </Button>
          {canWrite && (a.uploader?.id === user?.id || isAdmin) && (
            <Button
              size="sm"
              variant="ghost"
              iconOnly
              aria-label={`Delete ${a.filename}`}
              onClick={async () => {
                if (await confirm({ title: "Delete attachment?", description: `${a.filename} will be permanently deleted.`, confirmLabel: "Delete", destructive: true }))
                  del.mutate(a.id);
              }}
            >
              <Trash2 size={14} />
            </Button>
          )}
        </div>
      ))}
    </section>
  );
}

function Dependencies({ task, board, canWrite, onOpen }: { task: TaskDetail; board: Board; canWrite: boolean; onOpen: (id: string) => void }) {
  const qc = useQueryClient();
  const { error: toastError } = useToast();
  const [pick, setPick] = useState("");
  const [err, setErr] = useState<string>();
  const add = useMutation({
    mutationFn: (id: string) => api.post<Task>(`/tasks/${task.id}/dependencies`, { depends_on_id: id }),
    onSuccess: (t) => {
      applyTaskSnapshot(qc, t);
      qc.invalidateQueries({ queryKey: qk.task(task.id) });
      setPick("");
      setErr(undefined);
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not add dependency"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del<Task>(`/tasks/${task.id}/dependencies/${id}`),
    onSuccess: (t) => {
      applyTaskSnapshot(qc, t);
      qc.invalidateQueries({ queryKey: qk.task(task.id) });
    },
    onError: (e) => toastError(e, "Could not remove dependency"),
  });
  const existing = new Set(task.depends_on.map((d) => d.id));
  const candidates = sortTasks(board.tasks).filter((t) => t.id !== task.id && !existing.has(t.id)).sort((a, b) => a.number - b.number);
  const row = (d: TaskRef, removable: boolean) => (
    <div key={d.id} className="dep-row">
      <button type="button" className="btn btn-ghost btn-sm" style={{ padding: "0 4px" }} onClick={() => onOpen(d.id)}>
        <span className="mono">
          {board.project.key}-{d.number}
        </span>
      </button>
      <span className="title" title={d.title}>
        {d.title}
      </span>
      {d.done ? <Badge tone="success">done</Badge> : <Badge tone="warning">open</Badge>}
      {removable && canWrite && (
        <Button size="sm" variant="ghost" iconOnly aria-label={`Remove dependency on ${d.title}`} onClick={() => remove.mutate(d.id)}>
          <X size={14} />
        </Button>
      )}
    </div>
  );
  return (
    <section aria-labelledby="deps-h" className="stack" style={{ gap: 6 }}>
      <h3 id="deps-h" className="section-title">
        <Link2 size={12} /> Depends on
      </h3>
      {task.depends_on.length === 0 && <p className="faint" style={{ fontSize: 13 }}>No dependencies.</p>}
      {task.depends_on.map((d) => row(d, true))}
      {canWrite && candidates.length > 0 && (
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            if (pick) add.mutate(pick);
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <SelectField label="Add dependency" hideLabel value={pick} onChange={(e) => setPick(e.target.value)} error={err}>
              <option value="">Add a dependency…</option>
              {candidates.map((t) => (
                <option key={t.id} value={t.id}>
                  {board.project.key}-{t.number} {t.title}
                </option>
              ))}
            </SelectField>
          </div>
          <Button type="submit" size="sm" disabled={!pick} loading={add.isPending}>
            Add
          </Button>
        </form>
      )}
      {task.blocking.length > 0 && (
        <>
          <h3 className="section-title" style={{ marginTop: 8 }}>
            Blocking
          </h3>
          {task.blocking.map((d) => row(d, false))}
        </>
      )}
    </section>
  );
}

function History({ taskId, projectKey }: { taskId: string; projectKey: string }) {
  const { data, isLoading } = useTaskHistory(taskId);
  if (isLoading) return <Spinner />;
  return (
    <section aria-labelledby="hist-h">
      <h3 id="hist-h" className="section-title">
        History
      </h3>
      <ol className="timeline">
        {data?.map((e) => (
          <li key={e.id}>
            <Avatar name={e.actor?.display_name ?? "?"} size={22} />
            <div className="timeline-text">
              <strong>{e.actor?.display_name ?? "Someone"}</strong> {describeActivity(e, projectKey)}
              <div className="faint" style={{ fontSize: 12 }} title={formatDateTime(e.created_at)}>
                {relativeTime(e.created_at)}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function TaskDialog({
  taskId,
  board,
  presence,
  onClose,
  onOpen,
}: {
  taskId: string;
  board: Board;
  presence: PresenceUser[];
  onClose: () => void;
  onOpen: (id: string) => void;
}) {
  const { user } = useAuth();
  const { data: task, isLoading, error } = useTaskDetail(taskId);
  const update = useUpdateTask(board.project.id);
  const move = useMoveTask(board.project.id);
  const del = useDeleteTask(board.project.id);
  const qc = useQueryClient();
  const confirm = useConfirm();
  const { toast, error: toastError } = useToast();
  const [title, setTitle] = useState("");
  const [titleErr, setTitleErr] = useState<string>();
  const [desc, setDesc] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ConflictState | null>(null);
  const canWrite = board.can_edit;
  const isAdmin = board.role === "owner" || board.role === "admin"; // UI hint only; enforced server-side
  const viewers = presence.filter((p) => p.user_id !== user?.id && p.viewing_task_ids.includes(taskId));

  useEffect(() => {
    if (task) setTitle(task.title);
  }, [task?.id, task?.title]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = (patch: Omit<TaskPatch, "version">, version?: number) => {
    if (!task) return;
    update.mutate(
      { id: task.id, patch: { ...patch, version: version ?? task.version } },
      {
        onSuccess: () => setConflict(null),
        onError: (e) => {
          if (e instanceof ApiError && e.isConflict) {
            const current = (e.details as { current?: Task })?.current;
            if (current) {
              applyTaskSnapshot(qc, current);
              setConflict({ patch, current });
            }
            qc.invalidateQueries({ queryKey: qk.task(task.id) });
          } else toastError(e, "Could not save changes");
        },
      },
    );
  };

  if (error)
    return (
      <Modal open onOpenChange={(o) => !o && onClose()} title="Task unavailable">
        <ErrorState error={error} />
      </Modal>
    );

  const overdue = task ? isOverdue(task.due_date, task.completed_at) : false;

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      className="task-dialog"
      title={
        task ? (
          <span className="row row-wrap">
            <span className="mono faint">
              {board.project.key}-{task.number}
            </span>
            {task.blocked && <Badge tone="warning">Blocked</Badge>}
            {task.completed_at && <Badge tone="success">Done</Badge>}
            {overdue && <Badge tone="danger">Overdue</Badge>}
            {viewers.length > 0 && <span className="faint" style={{ fontSize: 12, fontWeight: 400 }}>{viewers.map((v) => v.display_name).join(", ")} also viewing</span>}
          </span>
        ) : (
          "Loading task"
        )
      }
    >
      {isLoading || !task ? (
        <LoadingState />
      ) : (
        <div className="stack stack-lg">
          {conflict && (
            <ConflictBanner
              conflict={conflict}
              busy={update.isPending}
              onReload={() => {
                setConflict(null);
                setDesc(null);
                setTitle(conflict.current.title);
              }}
              onOverwrite={() => save(conflict.patch, conflict.current.version)}
            />
          )}
          <div className="task-layout">
            <div className="stack stack-lg" style={{ minWidth: 0 }}>
              <TextField
                label="Title"
                value={title}
                maxLength={200}
                disabled={!canWrite}
                error={titleErr}
                data-testid="task-title-input"
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                onBlur={() => {
                  const parsed = taskTitleSchema.safeParse(title);
                  if (!parsed.success) return setTitleErr(parsed.error.issues[0].message);
                  setTitleErr(undefined);
                  if (parsed.data !== task.title) save({ title: parsed.data });
                }}
              />
              <div className="stack" style={{ gap: 6 }}>
                <TextAreaField
                  label="Description"
                  value={desc ?? task.description}
                  disabled={!canWrite}
                  rows={6}
                  maxLength={20000}
                  placeholder={canWrite ? "Add more detail…" : "No description"}
                  onChange={(e) => setDesc(e.target.value)}
                />
                {desc !== null && desc !== task.description && (
                  <div className="row">
                    <Button
                      size="sm"
                      variant="primary"
                      loading={update.isPending}
                      onClick={() => {
                        save({ description: desc });
                        setDesc(null);
                      }}
                    >
                      Save description
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setDesc(null)}>
                      Cancel
                    </Button>
                  </div>
                )}
              </div>
              <Attachments task={task} canWrite={canWrite} isAdmin={isAdmin} />
              <Comments task={task} canWrite={canWrite} isAdmin={isAdmin} />
              <History taskId={task.id} projectKey={board.project.key} />
            </div>
            <aside className="task-side" aria-label="Task properties">
              <SelectField
                label="Status"
                value={task.column_id}
                disabled={!canWrite || move.isPending}
                data-testid="task-status-select"
                onChange={(e) => {
                  const colId = e.target.value;
                  const count = board.tasks.filter((t) => t.column_id === colId && t.id !== task.id).length;
                  move.mutate(
                    { task, columnId: colId, index: count },
                    {
                      onSuccess: () => qc.invalidateQueries({ queryKey: qk.task(task.id) }),
                      onError: (err) => toastError(err, "Could not move task"),
                    },
                  );
                }}
              >
                {board.columns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </SelectField>
              <SelectField label="Priority" value={task.priority} disabled={!canWrite} onChange={(e) => save({ priority: e.target.value })}>
                {Object.entries(PRIORITY_LABEL).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </SelectField>
              <div className="row" style={{ alignItems: "end" }}>
                <div style={{ flex: 1 }}>
                  <TextField
                    label="Due date"
                    type="date"
                    value={task.due_date ?? ""}
                    disabled={!canWrite}
                    onChange={(e) => save({ due_date: e.target.value || null })}
                  />
                </div>
                {task.due_date && canWrite && (
                  <Button size="md" variant="ghost" iconOnly aria-label="Clear due date" onClick={() => save({ due_date: null })}>
                    <X size={16} />
                  </Button>
                )}
              </div>
              <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
                <legend className="field-label" style={{ marginBottom: 6 }}>
                  Assignees
                </legend>
                <div className="picker">
                  {board.members.map((m) => {
                    const checked = task.assignees.some((a) => a.id === m.id);
                    return (
                      <label key={m.id}>
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={!canWrite}
                          onChange={() =>
                            save({
                              assignee_ids: checked ? task.assignees.filter((a) => a.id !== m.id).map((a) => a.id) : [...task.assignees.map((a) => a.id), m.id],
                            })
                          }
                        />
                        <Avatar name={m.display_name} size={20} /> {m.display_name}
                      </label>
                    );
                  })}
                </div>
              </fieldset>
              <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
                <legend className="field-label" style={{ marginBottom: 6 }}>
                  Labels
                </legend>
                {board.labels.length === 0 ? (
                  <p className="faint" style={{ fontSize: 13 }}>
                    No labels yet — create them in project settings.
                  </p>
                ) : (
                  <div className="picker">
                    {board.labels.map((l) => {
                      const checked = task.labels.some((x) => x.id === l.id);
                      return (
                        <label key={l.id}>
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={!canWrite}
                            onChange={() =>
                              save({ label_ids: checked ? task.labels.filter((x) => x.id !== l.id).map((x) => x.id) : [...task.labels.map((x) => x.id), l.id] })
                            }
                          />
                          <span className="label-chip" style={{ ["--chip" as string]: l.color }}>
                            {l.name}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </fieldset>
              <Dependencies task={task} board={board} canWrite={canWrite} onOpen={onOpen} />
              <div className="faint" style={{ fontSize: 12 }}>
                Created {formatDateTime(task.created_at)}
                <br />
                Updated {relativeTime(task.updated_at)} · v{task.version}
              </div>
              {canWrite && (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={async () => {
                    const ok = await confirm({
                      title: `Delete ${board.project.key}-${task.number}?`,
                      description: "The task, its comments, attachments and dependency links will be permanently deleted.",
                      confirmLabel: "Delete task",
                      destructive: true,
                    });
                    if (!ok) return;
                    del.mutate(task.id, {
                      onSuccess: () => toast({ title: "Task deleted" }),
                      onError: (e) => toastError(e, "Could not delete task"),
                    });
                    onClose();
                  }}
                >
                  <Trash2 size={14} /> Delete task
                </Button>
              )}
            </aside>
          </div>
        </div>
      )}
    </Modal>
  );
}
