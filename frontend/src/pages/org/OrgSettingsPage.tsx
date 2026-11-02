import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Trash2, UserPlus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { qk, useInvitations, useInvite, useMembers, useOrg } from "@/lib/queries";
import { emailSchema } from "@/lib/validation";
import { relativeTime } from "@/lib/format";
import type { Invitation, Role } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { SelectField, TextField } from "@/components/ui/Field";
import { Avatar, Badge, ErrorState, LoadingState } from "@/components/ui/Feedback";
import { useConfirm } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";

const ROLE_HELP: Record<Role, string> = {
  owner: "Full control, including deleting the organization",
  admin: "Manage members, invitations and all projects",
  member: "Create and edit tasks in assigned projects",
  viewer: "Read-only access to assigned projects",
};

export function OrgSettingsPage() {
  const { orgId = "" } = useParams();
  const { user } = useAuth();
  const org = useOrg(orgId);
  const members = useMembers(orgId);
  const isAdmin = org.data?.role === "owner" || org.data?.role === "admin";
  const isOwner = org.data?.role === "owner";
  const invitations = useInvitations(orgId, !!isAdmin);
  const invite = useInvite(orgId);
  const qc = useQueryClient();
  const confirm = useConfirm();
  const { toast, error: toastError } = useToast();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [emailError, setEmailError] = useState<string>();
  const [lastInvite, setLastInvite] = useState<Invitation | null>(null);
  const [orgName, setOrgName] = useState<string | null>(null);

  const changeRole = useMutation({
    mutationFn: (v: { userId: string; role: Role }) => api.patch(`/orgs/${orgId}/members/${v.userId}`, { role: v.role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.members(orgId) }),
    onError: (e) => toastError(e, "Could not change role"),
  });
  const removeMember = useMutation({
    mutationFn: (userId: string) => api.del(`/orgs/${orgId}/members/${userId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.members(orgId) }),
    onError: (e) => toastError(e, "Could not remove member"),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api.del(`/orgs/${orgId}/invitations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.invitations(orgId) }),
  });
  const rename = useMutation({
    mutationFn: (name: string) => api.patch(`/orgs/${orgId}`, { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.org(orgId) });
      qc.invalidateQueries({ queryKey: qk.orgs });
      toast({ title: "Organization renamed", variant: "success" });
      setOrgName(null);
    },
    onError: (e) => toastError(e, "Could not rename"),
  });
  const deleteOrg = useMutation({
    mutationFn: () => api.del(`/orgs/${orgId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.orgs });
      toast({ title: "Organization deleted" });
      navigate("/orgs");
    },
    onError: (e) => toastError(e, "Could not delete organization"),
  });

  const submitInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = emailSchema.safeParse(email);
    if (!parsed.success) return setEmailError(parsed.error.issues[0].message);
    setEmailError(undefined);
    try {
      const inv = await invite.mutateAsync({ email: parsed.data, role });
      setLastInvite(inv);
      setEmail("");
      toast({ title: "Invitation sent", description: `${inv.email} was invited as ${inv.role}.`, variant: "success" });
    } catch (err) {
      setEmailError(err instanceof ApiError ? err.message : "Could not send invitation");
    }
  };

  if (org.isLoading || members.isLoading) return <LoadingState />;
  if (org.error) return <ErrorState error={org.error} />;

  return (
    <div className="stack stack-lg" style={{ maxWidth: 900 }}>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div>
          <h1>Members & settings</h1>
          <p className="subtitle">{org.data?.name} · your role: {org.data?.role}</p>
        </div>
      </div>

      {isAdmin && (
        <section className="card card-pad stack" aria-labelledby="invite-h">
          <h2 id="invite-h">Invite people</h2>
          <form className="form-grid" onSubmit={submitInvite} noValidate style={{ alignItems: "start" }}>
            <TextField label="Email address" type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={emailError} />
            <SelectField label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)} hint={ROLE_HELP[role]}>
              {isOwner && <option value="owner">Owner</option>}
              <option value="admin">Admin</option>
              <option value="member">Member</option>
              <option value="viewer">Viewer</option>
            </SelectField>
            <div className="field">
              <span className="field-label" aria-hidden>
                &nbsp;
              </span>
              <Button type="submit" variant="primary" loading={invite.isPending}>
                <UserPlus size={16} /> Send invite
              </Button>
            </div>
          </form>
          {lastInvite?.invite_url && (
            <div className="row row-wrap" style={{ background: "var(--surface-2)", padding: 10, borderRadius: 8 }}>
              <span className="muted">Share this link if email isn't configured:</span>
              <code className="mono" style={{ overflowWrap: "anywhere", flex: 1 }} data-testid="invite-link">
                {lastInvite.invite_url}
              </code>
              <Button
                size="sm"
                onClick={() => navigator.clipboard?.writeText(lastInvite.invite_url!).then(() => toast({ title: "Link copied" }))}
              >
                <Copy size={14} /> Copy
              </Button>
            </div>
          )}
          {!!invitations.data?.length && (
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Pending invitations</caption>
                <thead>
                  <tr>
                    <th>Pending invitation</th>
                    <th>Role</th>
                    <th>Expires</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {invitations.data.map((i) => (
                    <tr key={i.id}>
                      <td>{i.email}</td>
                      <td>{i.role}</td>
                      <td>{relativeTime(i.expires_at)}</td>
                      <td style={{ textAlign: "right" }}>
                        <Button size="sm" variant="ghost" onClick={() => revoke.mutate(i.id)}>
                          Revoke
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      <section className="card" aria-labelledby="members-h">
        <div className="card-header">
          <h2 id="members-h">Members</h2>
          <Badge>{members.data?.length ?? 0}</Badge>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {members.data?.map((m) => {
                const self = m.user.id === user?.id;
                const canEdit = isAdmin && !self && (isOwner || m.role !== "owner");
                return (
                  <tr key={m.user.id}>
                    <td>
                      <span className="row">
                        <Avatar name={m.user.display_name} size={24} /> {m.user.display_name} {self && <Badge>you</Badge>}
                      </span>
                    </td>
                    <td className="muted">{m.user.email}</td>
                    <td>
                      {canEdit ? (
                        <SelectField
                          label={`Role for ${m.user.display_name}`}
                          hideLabel
                          value={m.role}
                          onChange={(e) => changeRole.mutate({ userId: m.user.id, role: e.target.value as Role })}
                        >
                          {isOwner && <option value="owner">Owner</option>}
                          <option value="admin">Admin</option>
                          <option value="member">Member</option>
                          <option value="viewer">Viewer</option>
                        </SelectField>
                      ) : (
                        <Badge tone={m.role === "owner" ? "primary" : "neutral"}>{m.role}</Badge>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {(canEdit || self) && (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={self ? "Leave organization" : `Remove ${m.user.display_name}`}
                          onClick={async () => {
                            const ok = await confirm({
                              title: self ? "Leave organization?" : `Remove ${m.user.display_name}?`,
                              description: self
                                ? "You will lose access to all projects in this organization."
                                : "They will lose access immediately and be unassigned from all tasks in this organization.",
                              confirmLabel: self ? "Leave" : "Remove",
                              destructive: true,
                            });
                            if (!ok) return;
                            await removeMember.mutateAsync(m.user.id);
                            if (self) {
                              qc.invalidateQueries({ queryKey: qk.orgs });
                              navigate("/orgs");
                            }
                          }}
                        >
                          <Trash2 size={15} /> {self ? "Leave" : "Remove"}
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {isAdmin && (
        <section className="card card-pad stack" aria-labelledby="general-h">
          <h2 id="general-h">General</h2>
          <form
            className="row row-wrap"
            style={{ alignItems: "end" }}
            onSubmit={(e) => {
              e.preventDefault();
              if (orgName?.trim()) rename.mutate(orgName.trim());
            }}
          >
            <div style={{ flex: 1, minWidth: 220 }}>
              <TextField label="Organization name" value={orgName ?? org.data?.name ?? ""} maxLength={100} onChange={(e) => setOrgName(e.target.value)} />
            </div>
            <Button type="submit" disabled={!orgName?.trim() || orgName === org.data?.name} loading={rename.isPending}>
              Save
            </Button>
          </form>
        </section>
      )}

      {isOwner && (
        <section className="card card-pad stack" aria-labelledby="danger-h" style={{ borderColor: "var(--danger)" }}>
          <h2 id="danger-h">Danger zone</h2>
          <p className="muted">Deleting the organization permanently removes all projects, tasks, comments, attachments and history.</p>
          <div>
            <Button
              variant="danger"
              loading={deleteOrg.isPending}
              onClick={async () => {
                const ok = await confirm({
                  title: `Delete ${org.data?.name}?`,
                  description: "This cannot be undone. Every project, task, comment, attachment and activity record will be deleted.",
                  confirmLabel: "Delete organization",
                  destructive: true,
                });
                if (ok) deleteOrg.mutate();
              }}
            >
              Delete organization
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
