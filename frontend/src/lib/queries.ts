import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { dropTarget, moveTaskLocally, removeTask, upsertTask } from "./board";
import type {
  ActivityEvent,
  Board,
  Dashboard,
  DependencyGraph,
  Invitation,
  InvitationPreview,
  Member,
  Org,
  Project,
  ProjectSummary,
  Role,
  Session,
  Task,
  TaskDetail,
} from "./types";

export const qk = {
  orgs: ["orgs"] as const,
  org: (id: string) => ["org", id] as const,
  members: (orgId: string) => ["members", orgId] as const,
  invitations: (orgId: string) => ["invitations", orgId] as const,
  projects: (orgId: string, status?: string) => ["projects", orgId, status ?? "active"] as const,
  board: (projectId: string) => ["board", projectId] as const,
  task: (taskId: string) => ["task", taskId] as const,
  history: (taskId: string) => ["history", taskId] as const,
  tasks: (projectId: string, params: unknown) => ["tasks", projectId, params] as const,
  activity: (projectId: string) => ["activity", projectId] as const,
  orgActivity: (orgId: string) => ["org-activity", orgId] as const,
  graph: (projectId: string) => ["graph", projectId] as const,
  dashboard: (orgId: string, projectId?: string, days?: number) => ["dashboard", orgId, projectId ?? "all", days ?? 30] as const,
  sessions: ["sessions"] as const,
  projectMembers: (projectId: string) => ["project-members", projectId] as const,
};

// ------------------------------------------------------------------ orgs
export const useOrgs = () => useQuery({ queryKey: qk.orgs, queryFn: () => api.get<Org[]>("/orgs") });
export const useOrg = (id: string) => useQuery({ queryKey: qk.org(id), queryFn: () => api.get<Org>(`/orgs/${id}`) });
export const useMembers = (orgId: string) =>
  useQuery({ queryKey: qk.members(orgId), queryFn: () => api.get<Member[]>(`/orgs/${orgId}/members`), staleTime: 0 });
export const useInvitations = (orgId: string, enabled = true) =>
  useQuery({ queryKey: qk.invitations(orgId), queryFn: () => api.get<Invitation[]>(`/orgs/${orgId}/invitations`), enabled, staleTime: 0 });
export const useInvitationPreview = (token: string) =>
  useQuery({
    queryKey: ["invitation-preview", token],
    queryFn: () => api.get<InvitationPreview>("/invitations/preview", { token }),
    enabled: !!token,
    retry: false,
  });

export function useCreateOrg() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<Org>("/orgs", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.orgs }),
  });
}

export function useInvite(orgId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { email: string; role: Role }) => api.post<Invitation>(`/orgs/${orgId}/invitations`, v),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.invitations(orgId) }),
  });
}

// ------------------------------------------------------------------ projects
export const useProjects = (orgId: string, status: "active" | "archived" = "active") =>
  useQuery({
    queryKey: qk.projects(orgId, status),
    queryFn: () => api.get<ProjectSummary[]>(`/orgs/${orgId}/projects`, { status }),
  });

export const useBoard = (projectId: string) =>
  useQuery({ queryKey: qk.board(projectId), queryFn: () => api.get<Board>(`/projects/${projectId}/board`) });

export const useTaskDetail = (taskId: string | null) =>
  useQuery({
    queryKey: qk.task(taskId ?? ""),
    queryFn: () => api.get<TaskDetail>(`/tasks/${taskId}`),
    enabled: !!taskId,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });

export const useTaskHistory = (taskId: string | null) =>
  useQuery({
    queryKey: qk.history(taskId ?? ""),
    queryFn: () => api.get<ActivityEvent[]>(`/tasks/${taskId}/history`),
    enabled: !!taskId,
  });

export const useGraph = (projectId: string) =>
  useQuery({ queryKey: qk.graph(projectId), queryFn: () => api.get<DependencyGraph>(`/projects/${projectId}/dependency-graph`) });

export const useDashboard = (orgId: string, projectId?: string, days = 30) =>
  useQuery({
    queryKey: qk.dashboard(orgId, projectId, days),
    queryFn: () => api.get<Dashboard>(`/orgs/${orgId}/dashboard`, { project_id: projectId, days }),
  });

export const useSessions = () => useQuery({ queryKey: qk.sessions, queryFn: () => api.get<Session[]>("/auth/sessions") });

// ------------------------------------------------------------------ task mutations

function patchBoard(qc: QueryClient, projectId: string, fn: (b: Board) => Board) {
  qc.setQueryData<Board>(qk.board(projectId), (b) => (b ? fn(b) : b));
}

/** After any task write, keep detail + board caches coherent with the server's snapshot. */
export function applyTaskSnapshot(qc: QueryClient, task: Task) {
  patchBoard(qc, task.project_id, (b) => upsertTask(b, task));
  qc.setQueryData<TaskDetail>(qk.task(task.id), (d) => (d && d.version <= task.version ? { ...d, ...task } : d));
}

export function useCreateTask(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<Task>(`/projects/${projectId}/tasks`, body),
    onSuccess: (task) => {
      applyTaskSnapshot(qc, task);
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
    },
  });
}

export interface TaskPatch {
  version: number;
  title?: string;
  description?: string;
  priority?: string;
  due_date?: string | null;
  assignee_ids?: string[];
  label_ids?: string[];
}

/** Optimistic task edit with rollback; surfaces 409 conflicts to the caller. */
export function useUpdateTask(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: TaskPatch }) => {
      const body: Record<string, unknown> = { ...patch };
      if (patch.due_date === null) {
        delete body.due_date;
        body.clear_due_date = true;
      }
      return api.patch<Task>(`/tasks/${id}`, body);
    },
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: qk.board(projectId) });
      const prevBoard = qc.getQueryData<Board>(qk.board(projectId));
      const prevDetail = qc.getQueryData<TaskDetail>(qk.task(id));
      const simple: Partial<Task> = {};
      if (patch.title !== undefined) simple.title = patch.title;
      if (patch.description !== undefined) simple.description = patch.description;
      if (patch.priority !== undefined) simple.priority = patch.priority as Task["priority"];
      if (patch.due_date !== undefined) simple.due_date = patch.due_date;
      if (patch.assignee_ids && prevBoard)
        simple.assignees = prevBoard.members.filter((m) => patch.assignee_ids!.includes(m.id));
      if (patch.label_ids && prevBoard) simple.labels = prevBoard.labels.filter((l) => patch.label_ids!.includes(l.id));
      patchBoard(qc, projectId, (b) => ({ ...b, tasks: b.tasks.map((t) => (t.id === id ? { ...t, ...simple } : t)) }));
      if (prevDetail) qc.setQueryData<TaskDetail>(qk.task(id), { ...prevDetail, ...simple });
      return { prevBoard, prevDetail };
    },
    onError: (_e, { id }, ctx) => {
      if (ctx?.prevBoard) qc.setQueryData(qk.board(projectId), ctx.prevBoard);
      if (ctx?.prevDetail) qc.setQueryData(qk.task(id), ctx.prevDetail);
    },
    onSuccess: (task) => {
      applyTaskSnapshot(qc, task);
      qc.invalidateQueries({ queryKey: qk.history(task.id) });
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
    },
  });
}

/** Optimistic drag-and-drop move with rollback on failure. */
export function useMoveTask(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { task: Task; columnId: string; index: number }) => {
      const board = qc.getQueryData<Board>(qk.board(projectId));
      const target = board ? dropTarget(board, v.task.id, v.columnId, v.index) : { after_id: null, before_id: null };
      return api.post<Task>(`/tasks/${v.task.id}/move`, {
        version: v.task.version,
        column_id: v.columnId,
        after_id: target.after_id,
        before_id: target.before_id,
      });
    },
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: qk.board(projectId) });
      const prev = qc.getQueryData<Board>(qk.board(projectId));
      if (prev) {
        const { position } = dropTarget(prev, v.task.id, v.columnId, v.index);
        qc.setQueryData(qk.board(projectId), moveTaskLocally(prev, v.task.id, v.columnId, position));
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.board(projectId), ctx.prev);
      void qc.invalidateQueries({ queryKey: qk.board(projectId) });
    },
    onSuccess: (task) => {
      applyTaskSnapshot(qc, task);
      qc.invalidateQueries({ queryKey: qk.history(task.id) });
    },
  });
}

export function useDeleteTask(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => api.del(`/tasks/${taskId}`),
    onMutate: async (taskId) => {
      await qc.cancelQueries({ queryKey: qk.board(projectId) });
      const prev = qc.getQueryData<Board>(qk.board(projectId));
      if (prev) qc.setQueryData(qk.board(projectId), removeTask(prev, taskId));
      return { prev };
    },
    onError: (_e, _id, ctx) => ctx?.prev && qc.setQueryData(qk.board(projectId), ctx.prev),
    onSuccess: (_d, taskId) => {
      qc.removeQueries({ queryKey: qk.task(taskId) });
      qc.invalidateQueries({ queryKey: ["tasks", projectId] });
    },
  });
}

export type { Project };
