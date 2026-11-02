import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, CalendarClock, CheckCircle2, ListTodo, UserX } from "lucide-react";
import { api } from "@/lib/api";
import { useTheme } from "@/lib/theme";
import { qk, useDashboard, useProjects } from "@/lib/queries";
import type { ActivityEvent } from "@/lib/types";
import { SelectField } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/Feedback";
import { Button } from "@/components/ui/Button";
import { ActivityFeed } from "../project/ActivityPage";

function useChartColors() {
  const { resolved } = useTheme();
  return useMemo(() => {
    const cs = getComputedStyle(document.documentElement);
    const v = (n: string) => cs.getPropertyValue(n).trim();
    return { c1: v("--chart-1"), c2: v("--chart-2"), grid: v("--chart-grid"), text: v("--text-muted"), surface: v("--surface") };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved]);
}

function Stat({ label, value, icon, tone }: { label: string; value: string | number; icon: React.ReactNode; tone?: "danger" }) {
  return (
    <div className={`card stat${tone ? ` stat-${tone}` : ""}`}>
      <div className="stat-label row" style={{ gap: 6 }}>
        {icon} {label}
      </div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

const tooltipStyle = { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontSize: 12 };

export function DashboardPage() {
  const { orgId = "" } = useParams();
  const [projectId, setProjectId] = useState("");
  const [days, setDays] = useState(30);
  const projects = useProjects(orgId);
  const { data, isLoading, error, refetch } = useDashboard(orgId, projectId || undefined, days);
  const colors = useChartColors();
  const activity = useInfiniteQuery({
    queryKey: qk.orgActivity(orgId),
    queryFn: ({ pageParam }) => api.get<ActivityEvent[]>(`/orgs/${orgId}/activity`, { limit: 20, before: pageParam ?? undefined }),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => (last.length === 20 ? last[last.length - 1].id : null),
  });

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="subtitle">Live figures computed from your organization's tasks.</p>
        </div>
        <div className="spacer" />
        <div className="row row-wrap" style={{ alignItems: "end" }}>
          <SelectField label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">All projects</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </SelectField>
          <SelectField label="Trend period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </SelectField>
        </div>
      </div>
      {isLoading ? (
        <LoadingState />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : data.totals.tasks === 0 ? (
        <EmptyState title="No tasks yet">Create tasks in a project and your dashboard will fill in automatically.</EmptyState>
      ) : (
        <>
          <div className="stat-grid" data-testid="stats">
            <Stat label="Total tasks" value={data.totals.tasks} icon={<ListTodo size={14} />} />
            <Stat label="Open" value={data.totals.open} icon={<ListTodo size={14} />} />
            <Stat label={`Done · ${data.totals.completion_pct}%`} value={data.totals.done} icon={<CheckCircle2 size={14} />} />
            <Stat label="Overdue" value={data.totals.overdue} icon={<AlertTriangle size={14} />} tone={data.totals.overdue ? "danger" : undefined} />
            <Stat label="Due today" value={data.totals.due_today} icon={<CalendarClock size={14} />} />
            <Stat label="Unassigned open" value={data.unassigned_open} icon={<UserX size={14} />} />
          </div>
          <div className="chart-grid">
            <section className="card chart-card" aria-labelledby="status-h">
              <h2 id="status-h">Tasks by status</h2>
              <div className="chart-box" role="img" aria-label={data.by_status.map((s) => `${s.status}: ${s.count}`).join(", ")}>
                <ResponsiveContainer>
                  <BarChart data={data.by_status} layout="vertical" margin={{ left: 8, right: 36 }} barCategoryGap={6}>
                    <CartesianGrid horizontal={false} stroke={colors.grid} />
                    <XAxis type="number" allowDecimals={false} tick={{ fill: colors.text, fontSize: 12 }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="status" width={100} tick={{ fill: colors.text, fontSize: 12 }} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{ fill: colors.grid, opacity: 0.5 }} contentStyle={tooltipStyle} />
                    <Bar dataKey="count" name="Tasks" fill={colors.c1} radius={[0, 4, 4, 0]} maxBarSize={22}>
                      <LabelList dataKey="count" position="right" fill={colors.text} fontSize={12} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>
            <section className="card chart-card" aria-labelledby="trend-h">
              <h2 id="trend-h">Created vs completed</h2>
              <div className="chart-box">
                <ResponsiveContainer>
                  <LineChart data={data.trend} margin={{ left: -16, right: 12, top: 6 }}>
                    <CartesianGrid vertical={false} stroke={colors.grid} />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: colors.text, fontSize: 11 }}
                      tickFormatter={(d: string) => d.slice(5)}
                      minTickGap={24}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis allowDecimals={false} tick={{ fill: colors.text, fontSize: 12 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: colors.text, strokeDasharray: "3 3" }} />
                    <Line type="monotone" dataKey="created" name="Created" stroke={colors.c1} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: colors.surface, strokeWidth: 2 }} />
                    <Line type="monotone" dataKey="completed" name="Completed" stroke={colors.c2} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: colors.surface, strokeWidth: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="legend" aria-hidden>
                <span>
                  <i style={{ background: colors.c1 }} />
                  Created
                </span>
                <span>
                  <i style={{ background: colors.c2 }} />
                  Completed
                </span>
              </div>
              <details style={{ marginTop: 8 }}>
                <summary className="muted" style={{ cursor: "pointer", fontSize: 12 }}>
                  Show data table
                </summary>
                <div className="table-wrap" style={{ maxHeight: 220, overflow: "auto" }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Created</th>
                        <th>Completed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.trend.map((t) => (
                        <tr key={t.date}>
                          <td>{t.date}</td>
                          <td>{t.created}</td>
                          <td>{t.completed}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </section>
            <section className="card chart-card" aria-labelledby="proj-h">
              <h2 id="proj-h">Project completion</h2>
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }} className="stack">
                {data.projects.map((p) => (
                  <li key={p.id} className="stack" style={{ gap: 4 }}>
                    <div className="row">
                      <span className="key-pill">{p.key}</span>
                      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</span>
                      <span className="muted" style={{ fontVariantNumeric: "tabular-nums" }}>
                        {p.done}/{p.total} · {p.completion_pct}%
                      </span>
                    </div>
                    <div className="progress" role="progressbar" aria-valuenow={p.completion_pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${p.name} completion`}>
                      <span style={{ width: `${p.completion_pct}%` }} />
                    </div>
                    {p.overdue > 0 && (
                      <span className="due-overdue row" style={{ fontSize: 12, gap: 4 }}>
                        <AlertTriangle size={12} /> {p.overdue} overdue
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
            <section className="card chart-card" aria-labelledby="wl-h">
              <h2 id="wl-h">Workload</h2>
              {data.workload.length === 0 ? (
                <p className="muted">No tasks are assigned yet.</p>
              ) : (
                <div className="table-wrap">
                  <table className="table" data-testid="workload">
                    <thead>
                      <tr>
                        <th>Person</th>
                        <th>Open</th>
                        <th>Overdue</th>
                        <th>High/urgent</th>
                        <th>Done ({days}d)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.workload.map((w) => {
                        const max = Math.max(...data.workload.map((x) => x.open), 1);
                        return (
                          <tr key={w.user_id}>
                            <td>{w.display_name}</td>
                            <td>
                              <span className="row" style={{ gap: 6 }}>
                                <span style={{ width: 28, fontVariantNumeric: "tabular-nums" }}>{w.open}</span>
                                <span className="progress" style={{ width: 80 }}>
                                  <span style={{ width: `${(w.open / max) * 100}%`, background: colors.c1 }} />
                                </span>
                              </span>
                            </td>
                            <td className={w.overdue ? "due-overdue" : undefined}>{w.overdue}</td>
                            <td>{w.high_priority}</td>
                            <td>{w.completed_recently}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </>
      )}
      <section className="card chart-card" style={{ marginTop: "var(--space-4)" }} aria-labelledby="act-h">
        <h2 id="act-h">Activity timeline</h2>
        {activity.isLoading ? (
          <LoadingState />
        ) : (
          <>
            <ActivityFeed events={activity.data?.pages.flat() ?? []} />
            {activity.hasNextPage && (
              <div style={{ textAlign: "center", marginTop: 8 }}>
                <Button onClick={() => activity.fetchNextPage()} loading={activity.isFetchingNextPage}>
                  Load more
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </>
  );
}
