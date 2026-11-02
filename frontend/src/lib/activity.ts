import type { ActivityEvent } from "./types";

/** Human-readable sentence for an activity event (rendered as text; React escapes it). */
export function describeActivity(e: Pick<ActivityEvent, "type" | "payload">, key = ""): string {
  const p = e.payload ?? {};
  const ref = (t?: { number?: number; title?: string }) => (t ? `${key ? `${key}-${t.number} ` : ""}"${t.title ?? ""}"` : "a task");
  switch (e.type) {
    case "task.created":
      return `created ${ref(p.task)}`;
    case "task.updated": {
      const fields = Object.keys(p.changes ?? {}).map((f) => f.replace("_", " "));
      return `updated ${fields.join(", ") || "details"} of ${ref(p.task)}`;
    }
    case "task.assigned": {
      const a = p.changes?.assignees ?? {};
      const added = (a.added ?? []).map((x: any) => x.name).filter(Boolean);
      const removed = (a.removed ?? []).map((x: any) => x.name).filter(Boolean);
      const parts = [];
      if (added.length) parts.push(`assigned ${added.join(", ")}`);
      if (removed.length) parts.push(`unassigned ${removed.join(", ")}`);
      return `${parts.join(" and ") || "changed assignees"} on ${ref(p.task)}`;
    }
    case "task.moved":
      return `moved ${ref(p.task)} from ${p.from_column?.name} to ${p.to_column?.name}`;
    case "task.deleted":
      return `deleted ${ref(p.task)}`;
    case "comment.created":
      return `commented on "${p.task_title ?? "a task"}"`;
    case "comment.updated":
      return "edited a comment";
    case "comment.deleted":
      return "deleted a comment";
    case "attachment.added":
      return `attached ${p.filename} to "${p.task_title ?? "a task"}"`;
    case "attachment.deleted":
      return `removed attachment ${p.filename}`;
    case "dependency.added":
      return `made ${ref(p.task)} depend on ${ref(p.depends_on)}`;
    case "dependency.removed":
      return `removed a dependency from ${ref(p.task)}`;
    case "project.created":
      return `created project ${p.project?.name ?? ""}`;
    case "project.updated":
      return "updated project details";
    case "project.archived":
      return "archived the project";
    case "project.unarchived":
      return "restored the project";
    case "project.deleted":
      return `deleted project ${p.project?.name ?? ""} (${p.project?.task_count ?? 0} tasks)`;
    case "project.members_added":
      return `added ${(p.user_ids ?? []).length} member(s) to the project`;
    case "project.member_removed":
      return "removed a member from the project";
    case "column.created":
      return `added column ${p.column?.name}`;
    case "column.updated":
      return `updated column ${p.column?.name}`;
    case "column.deleted":
      return `deleted column ${p.name}${p.moved ? ` (moved ${p.moved} tasks)` : ""}`;
    case "column.reordered":
      return "reordered columns";
    case "column.rebalanced":
      return "re-spaced card positions";
    case "label.created":
      return `created label ${p.label?.name}`;
    case "label.updated":
      return `updated label ${p.label?.name}`;
    case "label.deleted":
      return "deleted a label";
    case "org.created":
      return `created the organization ${p.name ?? ""}`;
    case "org.updated":
      return "renamed the organization";
    case "member.joined":
      return `joined as ${p.role}`;
    case "member.left":
      return "left the organization";
    case "member.removed":
      return "removed a member";
    case "member.role_changed":
      return `changed a member's role from ${p.old} to ${p.new}`;
    case "invitation.created":
      return `invited ${p.email} as ${p.role}`;
    case "invitation.revoked":
      return `revoked the invitation for ${p.email}`;
    default:
      return e.type;
  }
}
