import { useGraph } from "@/lib/queries";
import { Badge, EmptyState, ErrorState, LoadingState } from "@/components/ui/Feedback";
import { useProjectCtx } from "./ProjectLayout";
import type { TaskRef } from "@/lib/types";

export function DependenciesPage() {
  const { projectId, board, openTask } = useProjectCtx();
  const { data, isLoading, error, refetch } = useGraph(projectId);
  if (isLoading) return <LoadingState />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const depCount = new Map<string, number>();
  for (const [t] of data.edges) depCount.set(t, (depCount.get(t) ?? 0) + 1);
  const key = board.project.key;

  const item = (n: TaskRef | undefined, extra?: React.ReactNode) =>
    n && (
      <li key={n.id} className="dep-row" style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
        <button className="btn btn-ghost btn-sm" onClick={() => openTask(n.id)}>
          <span className="mono">
            {key}-{n.number}
          </span>
        </button>
        <span className="title">{n.title}</span>
        {extra}
      </li>
    );

  if (data.edges.length === 0)
    return (
      <EmptyState title="No dependencies yet">
        Open a task and use “Depends on” to declare that it can't start until another task is done. ForgeBoard prevents cycles and computes
        which tasks are blocked or ready.
      </EmptyState>
    );

  return (
    <div className="chart-grid">
      <section className="card chart-card" aria-labelledby="ready-h">
        <h2 id="ready-h">
          Ready to start <Badge tone="success">{data.ready.length}</Badge>
        </h2>
        <p className="muted" style={{ marginBottom: 8 }}>
          Open tasks whose dependencies are all done, highest priority first.
        </p>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }} data-testid="ready-list">
          {data.ready.map((id) => item(byId.get(id)))}
        </ul>
      </section>
      <section className="card chart-card" aria-labelledby="blocked-h">
        <h2 id="blocked-h">
          Blocked <Badge tone="warning">{data.blocked.length}</Badge>
        </h2>
        <p className="muted" style={{ marginBottom: 8 }}>
          Open tasks waiting on at least one unfinished dependency.
        </p>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }} data-testid="blocked-list">
          {data.blocked.map((id) => item(byId.get(id), <span className="faint">{depCount.get(id)} deps</span>))}
        </ul>
      </section>
      <section className="card chart-card" style={{ gridColumn: "1 / -1" }} aria-labelledby="order-h">
        <h2 id="order-h">Execution order</h2>
        <p className="muted" style={{ marginBottom: 8 }}>
          A valid topological ordering: every task appears after all of its dependencies.
        </p>
        <ol style={{ margin: 0, paddingLeft: 24 }} data-testid="topo-order">
          {data.topological_order.map((id) => {
            const n = byId.get(id);
            return (
              n && (
                <li key={id} style={{ padding: "3px 0" }}>
                  <button className="th-sort" onClick={() => openTask(id)}>
                    <span className="mono">
                      {key}-{n.number}
                    </span>
                    &nbsp;{n.title}
                  </button>{" "}
                  {n.done && <Badge tone="success">done</Badge>}
                </li>
              )
            );
          })}
        </ol>
      </section>
    </div>
  );
}
