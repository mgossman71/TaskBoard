export type Role = "owner" | "admin" | "member" | "viewer";
export type Priority = "none" | "low" | "medium" | "high" | "urgent";
export type ProjectStatus = "active" | "archived";

export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}
export interface UserBrief {
  id: string;
  email: string;
  display_name: string;
}
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: User;
}
export interface Session {
  id: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  user_agent: string | null;
  ip_address: string | null;
  current: boolean;
}
export interface Org {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  role: Role;
}
export interface Member {
  user: UserBrief;
  role: Role;
  created_at: string;
}
export interface Invitation {
  id: string;
  email: string;
  role: Role;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  invite_url?: string;
}
export interface InvitationPreview {
  org_name: string;
  email: string;
  role: Role;
  expires_at: string;
}
export interface Project {
  id: string;
  org_id: string;
  name: string;
  key: string;
  description: string;
  status: ProjectStatus;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}
export interface ProjectSummary extends Project {
  task_count: number;
  done_count: number;
  member_count: number;
}
export interface Column {
  id: string;
  project_id: string;
  name: string;
  position: number;
  wip_limit: number | null;
  is_done: boolean;
}
export interface Label {
  id: string;
  project_id?: string;
  name: string;
  color: string;
}
export interface Task {
  id: string;
  project_id: string;
  column_id: string;
  number: number;
  title: string;
  /** Omitted from board payloads (cards); present on task detail/list responses. */
  description?: string;
  priority: Priority;
  due_date: string | null;
  position: number;
  version: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  assignees: UserBrief[];
  labels: Label[];
  blocked: boolean;
  dependency_ids: string[];
}
export interface TaskRef {
  id: string;
  number: number;
  title: string;
  column_id: string;
  done: boolean;
}
export interface Comment {
  id: string;
  task_id: string;
  author: UserBrief | null;
  body: string;
  created_at: string;
  edited_at: string | null;
}
export interface Attachment {
  id: string;
  task_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  uploader: UserBrief | null;
}
export interface TaskDetail extends Task {
  description: string;
  comments: Comment[];
  attachments: Attachment[];
  depends_on: TaskRef[];
  blocking: TaskRef[];
}
export interface Board {
  project: Project;
  columns: Column[];
  labels: Label[];
  members: UserBrief[];
  tasks: Task[];
  last_event_id: number;
  can_edit: boolean;
  role: Role;
}
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}
export interface ActivityEvent {
  id: number;
  type: string;
  project_id: string | null;
  task_id: string | null;
  actor: UserBrief | null;
  payload: Record<string, any>;
  created_at: string;
}
export interface DependencyGraph {
  nodes: TaskRef[];
  edges: [string, string][];
  topological_order: string[];
  blocked: string[];
  ready: string[];
}
export interface Dashboard {
  generated_at: string;
  totals: { tasks: number; done: number; open: number; overdue: number; due_today: number; completion_pct: number };
  by_status: { status: string; is_done: boolean; count: number }[];
  by_priority: Record<string, number>;
  projects: { id: string; name: string; key: string; total: number; done: number; overdue: number; completion_pct: number }[];
  workload: { user_id: string; display_name: string; open: number; overdue: number; high_priority: number; completed_recently: number }[];
  unassigned_open: number;
  trend: { date: string; created: number; completed: number }[];
  trend_days: number;
}
export interface PresenceUser {
  user_id: string;
  display_name: string;
  viewing_task_ids: string[];
}
