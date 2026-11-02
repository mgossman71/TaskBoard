import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderKanban, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useOrg, useProjects } from "@/lib/queries";
import { projectSchema } from "@/lib/validation";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Dialog";
import { TextAreaField, TextField } from "@/components/ui/Field";
import { Badge, EmptyState, ErrorState, LoadingState } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toast";

function suggestKey(name: string) {
  const words = name.toUpperCase().replace(/[^A-Z0-9 ]/g, "").split(/\s+/).filter(Boolean);
  let key = words.length > 1 ? words.map((w) => w[0]).join("") : (words[0] ?? "");
  key = key.replace(/^[0-9]+/, "").slice(0, 6);
  return key.length >= 2 ? key : (key + "PRJ").slice(0, 3);
}

function CreateProjectDialog({ orgId, open, onOpenChange }: { orgId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [formError, setFormError] = useState<string | null>(null);
  const { register, handleSubmit, formState, setValue, getValues, reset } = useForm<z.infer<typeof projectSchema>>({
    resolver: zodResolver(projectSchema),
    defaultValues: { name: "", key: "", description: "" },
  });
  const create = useMutation({
    mutationFn: (v: z.infer<typeof projectSchema>) => api.post<Project>(`/orgs/${orgId}/projects`, v),
  });
  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      const p = await create.mutateAsync(v);
      qc.invalidateQueries({ queryKey: ["projects", orgId] });
      toast({ title: `Project ${p.name} created`, variant: "success" });
      reset();
      onOpenChange(false);
      navigate(`/o/${orgId}/p/${p.id}/board`);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Could not create project");
    }
  });
  const nameReg = register("name");
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="New project" description="Projects get a Kanban board with To Do, In Progress, In Review and Done columns that you can customize.">
      <form className="stack" onSubmit={onSubmit} noValidate>
        {formError && <div className="form-error" role="alert">{formError}</div>}
        <TextField
          label="Project name"
          {...nameReg}
          onChange={(e) => {
            void nameReg.onChange(e);
            if (!formState.dirtyFields.key || !getValues("key")) setValue("key", suggestKey(e.target.value));
          }}
          error={formState.errors.name?.message}
        />
        <TextField
          label="Key"
          hint="Prefix for task ids, e.g. WEB-42"
          {...register("key", { setValueAs: (v: string) => v.toUpperCase() })}
          error={formState.errors.key?.message}
          maxLength={10}
        />
        <TextAreaField label="Description" {...register("description")} error={formState.errors.description?.message} />
        <div className="dialog-actions">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="primary" loading={formState.isSubmitting}>
            Create project
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function ProjectsPage() {
  const { orgId = "" } = useParams();
  const [tab, setTab] = useState<"active" | "archived">("active");
  const [creating, setCreating] = useState(false);
  const org = useOrg(orgId);
  const { data, isLoading, error, refetch } = useProjects(orgId, tab);
  const canCreate = org.data && org.data.role !== "viewer";

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{org.data?.name ?? "Projects"}</h1>
          <p className="subtitle">Projects you can access in this organization.</p>
        </div>
        <div className="spacer" />
        {canCreate && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={16} /> New project
          </Button>
        )}
      </div>
      <div className="tabs" role="tablist">
        {(["active", "archived"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`tab btn-ghost${tab === t ? " active" : ""}`}
            style={{ background: "none", border: 0, cursor: "pointer", font: "inherit" }}
            onClick={() => setTab(t)}
          >
            {t === "active" ? "Active" : "Archived"}
          </button>
        ))}
      </div>
      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : !data?.length ? (
        <EmptyState
          icon={<FolderKanban size={28} />}
          title={tab === "active" ? "No projects yet" : "No archived projects"}
          action={
            tab === "active" && canCreate ? (
              <Button variant="primary" onClick={() => setCreating(true)}>
                Create your first project
              </Button>
            ) : undefined
          }
        >
          {tab === "active" ? "Create a project to start organizing work on a Kanban board." : "Archived projects appear here."}
        </EmptyState>
      ) : (
        <div className="grid-cards">
          {data.map((p) => {
            const pct = p.task_count ? Math.round((p.done_count / p.task_count) * 100) : 0;
            return (
              <Link key={p.id} to={`/o/${orgId}/p/${p.id}/board`} className="card project-card" data-testid="project-card">
                <div className="row">
                  <span className="key-pill">{p.key}</span>
                  <h3 style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</h3>
                  {p.status === "archived" && <Badge tone="warning">Archived</Badge>}
                </div>
                {p.description && <p className="muted" style={{ overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>{p.description}</p>}
                <div className="progress" aria-label={`${pct}% complete`}>
                  <span style={{ width: `${pct}%` }} />
                </div>
                <div className="row muted" style={{ fontSize: 12 }}>
                  <span>
                    {p.done_count}/{p.task_count} tasks done
                  </span>
                  <span className="spacer" />
                  <span>{p.member_count} members</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
      <CreateProjectDialog orgId={orgId} open={creating} onOpenChange={setCreating} />
    </>
  );
}
