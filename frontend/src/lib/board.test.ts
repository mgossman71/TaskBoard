import { describe, expect, it } from "vitest";
import { dropTarget, moveTaskLocally, removeTask, tasksByColumn, upsertTask, withBlocked } from "./board";
import { board, task } from "@/test/fixtures";

describe("board helpers", () => {
  it("groups tasks by column ordered by position", () => {
    const b = board([task("b", "todo", 2048), task("a", "todo", 1024), task("c", "doing", 1)]);
    const g = tasksByColumn(b);
    expect(g.todo.map((t) => t.id)).toEqual(["a", "b"]);
    expect(g.doing.map((t) => t.id)).toEqual(["c"]);
    expect(g.done).toEqual([]);
  });

  it("upsert ignores stale snapshots (realtime events arriving out of order)", () => {
    const b = board([task("a", "todo", 1, { version: 3, title: "new" })]);
    const stale = upsertTask(b, task("a", "doing", 1, { version: 2, title: "old" }));
    expect(stale.tasks[0].title).toBe("new");
    const fresh = upsertTask(b, task("a", "doing", 1, { version: 4, title: "newest" }));
    expect(fresh.tasks[0]).toMatchObject({ title: "newest", column_id: "doing" });
    expect(upsertTask(b, task("z", "todo", 5)).tasks).toHaveLength(2);
  });

  it("recomputes blocked state from dependencies and done columns", () => {
    let b = board([task("dep", "todo", 1), task("t", "todo", 2, { dependency_ids: ["dep"] })]);
    b = withBlocked(b);
    expect(b.tasks.find((t) => t.id === "t")!.blocked).toBe(true);
    b = moveTaskLocally(b, "dep", "done", 1);
    expect(b.tasks.find((t) => t.id === "t")!.blocked).toBe(false);
    expect(b.tasks.find((t) => t.id === "dep")!.completed_at).not.toBeNull();
    b = moveTaskLocally(b, "dep", "doing", 1);
    expect(b.tasks.find((t) => t.id === "dep")!.completed_at).toBeNull();
    expect(b.tasks.find((t) => t.id === "t")!.blocked).toBe(true);
  });

  it("removing a task drops it from other tasks' dependencies", () => {
    const b = removeTask(withBlocked(board([task("dep", "todo", 1), task("t", "todo", 2, { dependency_ids: ["dep"] })])), "dep");
    expect(b.tasks.map((t) => t.id)).toEqual(["t"]);
    expect(b.tasks[0]).toMatchObject({ dependency_ids: [], blocked: false });
  });

  it("computes neighbours and optimistic positions for drops", () => {
    const b = board([task("a", "todo", 1024), task("b", "todo", 2048), task("m", "doing", 10)]);
    expect(dropTarget(b, "m", "todo", 0)).toEqual({ after_id: null, before_id: "a", position: 0 });
    expect(dropTarget(b, "m", "todo", 1)).toEqual({ after_id: "a", before_id: null, position: 1536 });
    expect(dropTarget(b, "m", "todo", 2)).toEqual({ after_id: "b", before_id: null, position: 3072 });
    expect(dropTarget(b, "m", "done", 0)).toEqual({ after_id: null, before_id: null, position: 1024 });
    // moving within the same column excludes the moving card
    expect(dropTarget(b, "a", "todo", 1)).toMatchObject({ after_id: "b" });
  });
});
