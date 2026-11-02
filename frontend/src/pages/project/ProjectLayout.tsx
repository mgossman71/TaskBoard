import { useCallback, useEffect } from "react";
import { NavLink, Outlet, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router";
import { Archive } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useBoard } from "@/lib/queries";
import { useConnectionStatus, useProjectRealtime } from "@/lib/useRealtime";
import { realtime } from "@/lib/realtime";
import type { Board, PresenceUser } from "@/lib/types";
import { Avatar, Badge, ErrorState, LoadingState } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toast";
import { TaskDialog } from "./TaskDialog";

export interface ProjectCtx {
  board: Board;
  orgId: string;
  projectId: string;
  presence: PresenceUser[];
  openTask: (id: string) => void;
}

export const useProjectCtx = () => useOutletContext<ProjectCtx>();

const STATUS_TEXT = { idle: "Offline", connecting: "Connecting…", connected: "Live", reconnecting: "Reconnecting…", offline: "Offline" };

export function ProjectLayout() {
  const { orgId = "", projectId = "" } = useParams();
  const { data: board, isLoading, error, refetch } = useBoard(projectId);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { toast } = useToast();
  const status = useConnectionStatus();
  const openTaskId = params.get("task");

  const { presence } = useProjectRealtime(projectId, board?.last_event_id, {
    onRevoked: () => {
      toast({ title: "Access removed", description: "You no longer have access to this project.", variant: "warning" });
      navigate(`/o/${orgId}/projects`);
    },
    onDeleted: () => {
      toast({ title: "Project deleted", description: "This project was deleted by an administrator.", variant: "warning" });
      navigate(`/o/${orgId}/projects`);
    },
    onEvent: (e) => {
      if (e.type === "task.assigned" && e.actor_id !== user?.id) {
        const added = (e.payload.changes?.assignees?.added ?? []) as { id: string }[];
        if (added.some((a) => a.id === user?.id)) {
          toast({ title: `${e.actor?.display_name ?? "Someone"} assigned you a task`, description: e.payload.task?.title });
        }
      }
    },
  });

  useEffect(() => {
    realtime.setViewing(projectId, openTaskId);
  }, [projectId, openTaskId, presence.length]);

  const openTask = useCallback(
    (id: string) => {
      const next = new URLSearchParams(params);
      next.set("task", id);
      setParams(next);
    },
    [params, setParams],
  );
  const closeTask = () => {
    const next = new URLSearchParams(params);
    next.delete("task");
    setParams(next, { replace: true });
  };

  if (isLoading) return <LoadingState label="Loading project…" />;
  if (error || !board) return <ErrorState error={error} onRetry={() => refetch()} />;

  const base = `/o/${orgId}/p/${projectId}`;
  return (
    <>
      <div className="page-header" style={{ marginBottom: "var(--space-3)" }}>
        <span className="key-pill">{board.project.key}</span>
        <h1 style={{ minWidth: 0, overflowWrap: "anywhere" }}>{board.project.name}</h1>
        {board.project.status === "archived" && (
          <Badge tone="warning">
            <Archive size={12} /> Archived · read-only
          </Badge>
        )}
        <div className="spacer" />
        <div className="avatar-stack" aria-label={`${presence.length} people viewing`} data-testid="presence">
          {presence.slice(0, 6).map((p) => (
            <Avatar key={p.user_id} name={p.display_name} size={28} title={`${p.display_name} is here`} />
          ))}
        </div>
        <span className={`conn conn-${status}`} role="status" aria-live="polite" data-testid="connection-status">
          {STATUS_TEXT[status]}
        </span>
      </div>
      <nav className="tabs" aria-label="Project views">
        <NavLink to={`${base}/board`} className="tab">
          Board
        </NavLink>
        <NavLink to={`${base}/list`} className="tab">
          List
        </NavLink>
        <NavLink to={`${base}/dependencies`} className="tab">
          Dependencies
        </NavLink>
        <NavLink to={`${base}/activity`} className="tab">
          Activity
        </NavLink>
        <NavLink to={`${base}/settings`} className="tab">
          Settings
        </NavLink>
      </nav>
      <Outlet context={{ board, orgId, projectId, presence, openTask } satisfies ProjectCtx} />
      {openTaskId && <TaskDialog taskId={openTaskId} board={board} presence={presence} onClose={closeTask} onOpen={openTask} />}
    </>
  );
}
