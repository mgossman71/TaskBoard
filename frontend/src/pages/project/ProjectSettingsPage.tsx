import { useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { qk, useMembers } from "@/lib/queries";
import type { Column, Project, UserBrief } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Modal, useConfirm } from "@/components/ui/Dialog";
import { SelectField, TextAreaField, TextField } from "@/components/ui/Field";
import { Avatar, Badge } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toast";
import { useProjectCtx } from "./ProjectLayout";

function useProjectMutation<T>(fn: (v: T) => Promise<unknown>, success?: string) {
  const { projectId, orgId } = useProjectCtx();
  const qc = useQueryClient();
  const { toast, error } = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.board(projectId) });
      qc.invalidateQueries({ queryKey: ["projects", orgId] });
      qc.invalidateQueries({ queryKey: qk.projectMembers(projectId) });
      if (success) toast({ title: success, variant: "success" });
    },
    onError: (e) => error(e, "Action failed"),
  });
}

function DeleteColumnDialog({ column, columns, onClose }: { column: Column; columns: Column[]; onClose: () => void }) {
  const { projectId, board } = useProjectCtx();
  const others = columns.filter((c) => c.id !== column.id);
  const count = board.tasks.filter((t) => t.column_id === column.id).length;
  const [target, setTarget] = useState(others[0]?.id ?? "");
  const del = useProjectMutation(() => api.del(`/projects/${projectId}/columns/${column.id}`, count ? { move_to: target } : undefined), "Column deleted");
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Delete column “${column.name}”?`} description={count ? `${count} task(s) will be moved to another column.` : "This column is empty."}>
      <div className="stack">
        {count > 0 && (
          <SelectField label="Move tasks to" value={target} onChange={(e) => setTarget(e.target.value)}>
            {others.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
        )}
        <div className="dialog-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={del.isPending} onClick={() => del.mutate(undefined, { onSuccess: onClose })}>
            Delete column
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function ColumnsSection() {
  const { board, projectId } = useProjectCtx();
  const columns = board.columns;
  const [name, setName] = useState("");
  const [nameErr, setNameErr] = useState<string>();
  const [deleting, setDeleting] = useState<Column | null>(null);
  const create = useProjectMutation((v: { name: string }) => api.post(`/projects/${projectId}/columns`, v), "Column added");
  const update = useProjectMutation((v: { id: string; body: Record<string, unknown> }) => api.patch(`/projects/${projectId}/columns/${v.id}`, v.body));
  const reorder = useProjectMutation((ids: string[]) => api.put(`/projects/${projectId}/columns/order`, { column_ids: ids }));
  const swap = (i: number, j: number) => {
    const ids = columns.map((c) => c.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    reorder.mutate(ids);
  };
  return (
    <section className="card" aria-labelledby="cols-h">
      <div className="card-header">
        <h2 id="cols-h">Board columns</h2>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Order</th>
              <th>Name</th>
              <th>WIP limit</th>
              <th>Counts as done</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {columns.map((c, i) => (
              <tr key={c.id}>
                <td>
                  <span className="row" style={{ gap: 2 }}>
                    <Button size="sm" variant="ghost" iconOnly aria-label={`Move ${c.name} left`} disabled={i === 0} onClick={() => swap(i, i - 1)}>
                      <ArrowUp size={14} />
                    </Button>
                    <Button size="sm" variant="ghost" iconOnly aria-label={`Move ${c.name} right`} disabled={i === columns.length - 1} onClick={() => swap(i, i + 1)}>
                      <ArrowDown size={14} />
                    </Button>
                  </span>
                </td>
                <td>
                  <TextField
                    label={`Name of column ${i + 1}`}
                    hideLabel
                    defaultValue={c.name}
                    maxLength={60}
                    onBlur={(e) => {
                      const v = e.target.value.trim();
                      if (v && v !== c.name) update.mutate({ id: c.id, body: { name: v } });
                      else e.target.value = c.name;
                    }}
                  />
                </td>
                <td style={{ width: 120 }}>
                  <TextField
                    label={`WIP limit for ${c.name}`}
                    hideLabel
                    type="number"
                    min={1}
                    max={1000}
                    placeholder="None"
                    defaultValue={c.wip_limit ?? ""}
                    onBlur={(e) => {
                      const raw = e.target.value;
                      const v = raw === "" ? null : Number(raw);
                      if (v === c.wip_limit) return;
                      if (v === null) update.mutate({ id: c.id, body: { clear_wip_limit: true } });
                      else if (Number.isInteger(v) && v >= 1 && v <= 1000) update.mutate({ id: c.id, body: { wip_limit: v } });
                    }}
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`${c.name} counts as done`}
                    checked={c.is_done}
                    onChange={(e) => update.mutate({ id: c.id, body: { is_done: e.target.checked } })}
                  />
                </td>
                <td style={{ textAlign: "right" }}>
                  <Button size="sm" variant="ghost" aria-label={`Delete column ${c.name}`} disabled={columns.length <= 1} onClick={() => setDeleting(c)}>
                    <Trash2 size={14} />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form
        className="row row-wrap"
        style={{ padding: 16, alignItems: "start" }}
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim()) return setNameErr("Column name is required");
          setNameErr(undefined);
          create.mutate({ name: name.trim() }, { onSuccess: () => setName("") });
        }}
      >
        <div style={{ flex: 1, minWidth: 200 }}>
          <TextField label="New column name" hideLabel placeholder="New column name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} error={nameErr} />
        </div>
        <Button type="submit" loading={create.isPending}>
          Add column
        </Button>
      </form>
      {deleting && <DeleteColumnDialog column={deleting} columns={columns} onClose={() => setDeleting(null)} />}
    </section>
  );
}

function LabelsSection({ canWrite }: { canWrite: boolean }) {
  const { board, projectId } = useProjectCtx();
  const [name, setName] = useState("");
  const [color, setColor] = useState("#4f46e5");
  const [err, setErr] = useState<string>();
  const create = useProjectMutation((v: { name: string; color: string }) => api.post(`/projects/${projectId}/labels`, v), "Label created");
  const del = useProjectMutation((id: string) => api.del(`/projects/${projectId}/labels/${id}`));
  return (
    <section className="card card-pad stack" aria-labelledby="labels-h">
      <h2 id="labels-h">Labels</h2>
      <div className="row row-wrap">
        {board.labels.length === 0 && <span className="faint">No labels yet.</span>}
        {board.labels.map((l) => (
          <span key={l.id} className="row" style={{ gap: 2 }}>
            <span className="label-chip" style={{ ["--chip" as string]: l.color }}>
              {l.name}
            </span>
            {canWrite && (
              <Button size="sm" variant="ghost" iconOnly aria-label={`Delete label ${l.name}`} onClick={() => del.mutate(l.id)}>
                <Trash2 size={12} />
              </Button>
            )}
          </span>
        ))}
      </div>
      {canWrite && (
        <form
          className="row row-wrap"
          style={{ alignItems: "start" }}
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return setErr("Label name is required");
            setErr(undefined);
            create.mutate({ name: name.trim(), color }, { onSuccess: () => setName(""), onError: (e2) => setErr(e2 instanceof ApiError ? e2.message : undefined) });
          }}
        >
          <div style={{ flex: 1, minWidth: 180 }}>
            <TextField label="Label name" hideLabel placeholder="Label name" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} error={err} />
          </div>
          <label className="sr-only" htmlFor="label-color">
            Label color
          </label>
          <input id="label-color" type="color" value={color} onChange={(e) => setColor(e.target.value)} style={{ height: 36, width: 48, border: 0, background: "none" }} />
          <Button type="submit" loading={create.isPending}>
            Add label
          </Button>
        </form>
      )}
    </section>
  );
}

function MembersSection() {
  const { projectId, orgId } = useProjectCtx();
  const orgMembers = useMembers(orgId);
  const pm = useQuery({
    queryKey: qk.projectMembers(projectId),
    queryFn: () => api.get<{ user: UserBrief; added_at: string }[]>(`/projects/${projectId}/members`),
  });
  const [pick, setPick] = useState("");
  const add = useProjectMutation((ids: string[]) => api.post(`/projects/${projectId}/members`, { user_ids: ids }), "Member added");
  const remove = useProjectMutation((id: string) => api.del(`/projects/${projectId}/members/${id}`), "Member removed");
  const confirm = useConfirm();
  const current = new Set(pm.data?.map((m) => m.user.id));
  const candidates = orgMembers.data?.filter((m) => !current.has(m.user.id)) ?? [];
  return (
    <section className="card card-pad stack" aria-labelledby="pm-h">
      <h2 id="pm-h">Project members</h2>
      <p className="muted">Organization owners and admins always have access. Members and viewers need to be added here.</p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {pm.data?.map((m) => (
          <li key={m.user.id} className="row" style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
            <Avatar name={m.user.display_name} size={24} /> {m.user.display_name} <span className="faint">{m.user.email}</span>
            <span className="spacer" />
            <Button
              size="sm"
              variant="ghost"
              onClick={async () => {
                if (
                  await confirm({
                    title: `Remove ${m.user.display_name} from this project?`,
                    description: "They will be unassigned from this project's tasks and lose access (unless they're an org admin).",
                    confirmLabel: "Remove",
                    destructive: true,
                  })
                )
                  remove.mutate(m.user.id);
              }}
            >
              Remove
            </Button>
          </li>
        ))}
      </ul>
      {candidates.length > 0 && (
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            if (pick) add.mutate([pick], { onSuccess: () => setPick("") });
          }}
        >
          <div style={{ flex: 1 }}>
            <SelectField label="Add member" hideLabel value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Add an organization member…</option>
              {candidates.map((m) => (
                <option key={m.user.id} value={m.user.id}>
                  {m.user.display_name} ({m.role})
                </option>
              ))}
            </SelectField>
          </div>
          <Button type="submit" disabled={!pick} loading={add.isPending}>
            Add
          </Button>
        </form>
      )}
    </section>
  );
}

function GeneralSection() {
  const { board, projectId } = useProjectCtx();
  const p = board.project;
  const [name, setName] = useState(p.name);
  const [desc, setDesc] = useState(p.description);
  const [err, setErr] = useState<string | null>(null);
  const qc = useQueryClient();
  const save = useProjectMutation((v: { name: string; description: string }) => api.patch<Project>(`/projects/${projectId}`, { ...v, version: p.version }), "Project updated");
  return (
    <section className="card card-pad stack" aria-labelledby="gen-h">
      <h2 id="gen-h">General</h2>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim()) return setErr("Name is required");
          setErr(null);
          save.mutate(
            { name: name.trim(), description: desc },
            {
              onError: (e2) => {
                if (e2 instanceof ApiError && e2.isConflict) {
                  setErr("Someone else changed this project. The latest values were loaded — review and save again.");
                  const cur = (e2.details as { current?: Project })?.current;
                  if (cur) {
                    setName(cur.name);
                    setDesc(cur.description);
                  }
                  qc.invalidateQueries({ queryKey: qk.board(projectId) });
                }
              },
            },
          );
        }}
      >
        {err && <div className="form-error" role="alert">{err}</div>}
        <TextField label="Project name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        <TextAreaField label="Description" value={desc} maxLength={5000} onChange={(e) => setDesc(e.target.value)} />
        <div>
          <Button type="submit" variant="primary" loading={save.isPending}>
            Save changes
          </Button>
        </div>
      </form>
    </section>
  );
}

export function ProjectSettingsPage() {
  const { board, projectId, orgId } = useProjectCtx();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { toast, error } = useToast();
  const isAdmin = board.role === "owner" || board.role === "admin";
  const archived = board.project.status === "archived";
  const archive = useProjectMutation(() => api.post(`/projects/${projectId}/${archived ? "unarchive" : "archive"}`), archived ? "Project restored" : "Project archived");
  const del = useMutation({
    mutationFn: () => api.del(`/projects/${projectId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", orgId] });
      qc.removeQueries({ queryKey: qk.board(projectId) });
      toast({ title: "Project deleted" });
      navigate(`/o/${orgId}/projects`);
    },
    onError: (e) => error(e, "Could not delete project"),
  });

  if (!isAdmin)
    return (
      <div className="stack stack-lg" style={{ maxWidth: 900 }}>
        <p className="muted">
          Only organization owners and admins can change project settings. Your role: <Badge>{board.role}</Badge>
        </p>
        <LabelsSection canWrite={board.can_edit} />
      </div>
    );

  return (
    <div className="stack stack-lg" style={{ maxWidth: 900 }}>
      {!archived && <GeneralSection />}
      {!archived && <ColumnsSection />}
      <LabelsSection canWrite={board.can_edit} />
      {!archived && <MembersSection />}
      <section className="card card-pad stack" aria-labelledby="danger-h" style={{ borderColor: "var(--danger)" }}>
        <h2 id="danger-h">Danger zone</h2>
        <div className="row row-wrap">
          <div style={{ flex: 1, minWidth: 220 }}>
            <strong>{archived ? "Restore project" : "Archive project"}</strong>
            <p className="muted">{archived ? "Make the project editable again." : "Archived projects are read-only and hidden from the active list."}</p>
          </div>
          <Button
            loading={archive.isPending}
            onClick={async () => {
              if (archived || (await confirm({ title: "Archive this project?", description: "It becomes read-only for everyone until restored.", confirmLabel: "Archive" })))
                archive.mutate(undefined);
            }}
          >
            {archived ? "Restore" : "Archive"}
          </Button>
        </div>
        <div className="row row-wrap">
          <div style={{ flex: 1, minWidth: 220 }}>
            <strong>Delete project</strong>
            <p className="muted">Permanently deletes all tasks, comments, attachments, dependencies and project history.</p>
          </div>
          <Button
            variant="danger"
            loading={del.isPending}
            onClick={async () => {
              const ok = await confirm({
                title: `Delete ${board.project.name}?`,
                description: `This permanently deletes ${board.tasks.length} task(s) and everything attached to them. This cannot be undone.`,
                confirmLabel: "Delete project",
                destructive: true,
              });
              if (ok) del.mutate();
            }}
          >
            Delete project
          </Button>
        </div>
      </section>
    </div>
  );
}
