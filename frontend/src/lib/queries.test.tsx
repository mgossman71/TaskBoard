import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { qk, useMoveTask, useUpdateTask } from "./queries";
import { applyEventToCache } from "./useRealtime";
import { board, task } from "@/test/fixtures";
import type { Board } from "./types";

function setup(initial: Board) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  qc.setQueryData(qk.board("p"), initial);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return { qc, wrapper };
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("optimistic mutations", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("moves a card immediately and rolls back when the server rejects it", async () => {
    let release!: () => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (release = () => resolve(json(409, { error: { code: "conflict", message: "WIP limit" } }))))),
    );
    const t = task("a", "todo", 1024);
    const { qc, wrapper } = setup(board([t]));
    const { result } = renderHook(() => useMoveTask("p"), { wrapper });
    act(() => result.current.mutate({ task: t, columnId: "doing", index: 0 }));
    await waitFor(() => expect(qc.getQueryData<Board>(qk.board("p"))!.tasks[0].column_id).toBe("doing"));
    act(() => release());
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(qc.getQueryData<Board>(qk.board("p"))!.tasks[0].column_id).toBe("todo");
  });

  it("applies the server snapshot on success", async () => {
    const t = task("a", "todo", 1024);
    vi.stubGlobal("fetch", vi.fn(async () => json(200, { ...t, title: "renamed", version: 2 })));
    const { qc, wrapper } = setup(board([t]));
    const { result } = renderHook(() => useUpdateTask("p"), { wrapper });
    await act(() => result.current.mutateAsync({ id: "a", patch: { version: 1, title: "renamed" } }));
    expect(qc.getQueryData<Board>(qk.board("p"))!.tasks[0]).toMatchObject({ title: "renamed", version: 2 });
  });

  it("rolls back an edit on a version conflict", async () => {
    const t = task("a", "todo", 1024, { title: "orig" });
    vi.stubGlobal("fetch", vi.fn(async () => json(409, { error: { code: "version_conflict", message: "x", details: { current: { ...t, version: 5 } } } })));
    const { qc, wrapper } = setup(board([t]));
    const { result } = renderHook(() => useUpdateTask("p"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ id: "a", patch: { version: 1, title: "mine" } }).catch(() => undefined);
    });
    expect(qc.getQueryData<Board>(qk.board("p"))!.tasks[0].title).toBe("orig");
  });
});

describe("realtime cache application", () => {
  it("applies task events and removals to the cached board", () => {
    const { qc } = setup(board([task("a", "todo", 1)]));
    applyEventToCache(qc, "p", {
      kind: "event", id: 10, type: "task.moved", org_id: "o", project_id: "p", task_id: "a", actor_id: "x", actor: null, created_at: "",
      payload: { task: task("a", "done", 5, { version: 2 }) },
    });
    let b = qc.getQueryData<Board>(qk.board("p"))!;
    expect(b.tasks[0]).toMatchObject({ column_id: "done", version: 2 });
    expect(b.last_event_id).toBe(10);
    applyEventToCache(qc, "p", {
      kind: "event", id: 11, type: "task.created", org_id: "o", project_id: "p", task_id: "b", actor_id: "x", actor: null, created_at: "",
      payload: { task: task("b", "todo", 1) },
    });
    applyEventToCache(qc, "p", {
      kind: "event", id: 12, type: "task.deleted", org_id: "o", project_id: "p", task_id: null, actor_id: "x", actor: null, created_at: "",
      payload: { task: { id: "a", number: 1, title: "a" } },
    });
    b = qc.getQueryData<Board>(qk.board("p"))!;
    expect(b.tasks.map((t) => t.id)).toEqual(["b"]);
  });
});
