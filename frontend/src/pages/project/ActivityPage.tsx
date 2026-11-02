import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { describeActivity } from "@/lib/activity";
import { formatDateTime, relativeTime } from "@/lib/format";
import { qk } from "@/lib/queries";
import type { ActivityEvent } from "@/lib/types";
import { Avatar, EmptyState, ErrorState, LoadingState } from "@/components/ui/Feedback";
import { Button } from "@/components/ui/Button";
import { useProjectCtx } from "./ProjectLayout";

export function ActivityFeed({ events, projectKey }: { events: ActivityEvent[]; projectKey?: string }) {
  return (
    <ol className="timeline" data-testid="activity-feed">
      {events.map((e) => (
        <li key={e.id}>
          <Avatar name={e.actor?.display_name ?? "?"} size={26} />
          <div className="timeline-text">
            <strong>{e.actor?.display_name ?? "Someone"}</strong> {describeActivity(e, projectKey)}
            <div className="faint" style={{ fontSize: 12 }} title={formatDateTime(e.created_at)}>
              {relativeTime(e.created_at)}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function ActivityPage() {
  const { projectId, board } = useProjectCtx();
  const q = useInfiniteQuery({
    queryKey: qk.activity(projectId),
    queryFn: ({ pageParam }) => api.get<ActivityEvent[]>(`/projects/${projectId}/activity`, { limit: 50, before: pageParam ?? undefined }),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => (last.length === 50 ? last[last.length - 1].id : null),
  });
  if (q.isLoading) return <LoadingState />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const events = q.data?.pages.flat() ?? [];
  if (!events.length) return <EmptyState title="No activity yet" />;
  return (
    <section className="card card-pad" style={{ maxWidth: 860 }}>
      <ActivityFeed events={events} projectKey={board.project.key} />
      {q.hasNextPage && (
        <div style={{ textAlign: "center", marginTop: 12 }}>
          <Button onClick={() => q.fetchNextPage()} loading={q.isFetchingNextPage}>
            Load older activity
          </Button>
        </div>
      )}
    </section>
  );
}
