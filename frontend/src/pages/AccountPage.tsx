import { useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api, ApiError, setTokens } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { qk, useSessions } from "@/lib/queries";
import { passwordSchema } from "@/lib/validation";
import { formatDateTime, relativeTime } from "@/lib/format";
import type { User } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { Badge, ErrorState, LoadingState } from "@/components/ui/Feedback";
import { useConfirm } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";

const changeSchema = z
  .object({ current: z.string().min(1, "Enter your current password"), password: passwordSchema, confirm: z.string() })
  .refine((d) => d.password === d.confirm, { path: ["confirm"], message: "Passwords do not match" });

export function AccountPage() {
  const { user, setUser, logout } = useAuth();
  const sessions = useSessions();
  const qc = useQueryClient();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const { toast, error: toastError } = useToast();
  const [name, setName] = useState(user?.display_name ?? "");
  const form = useForm<z.infer<typeof changeSchema>>({ resolver: zodResolver(changeSchema) });
  const [pwError, setPwError] = useState<string | null>(null);

  const saveName = useMutation({
    mutationFn: () => api.patch<User>("/auth/me", { display_name: name }),
    onSuccess: (u) => {
      setUser(u);
      toast({ title: "Profile updated", variant: "success" });
    },
    onError: (e) => toastError(e, "Could not update profile"),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api.del(`/auth/sessions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.sessions }),
  });

  const changePassword = form.handleSubmit(async (v) => {
    setPwError(null);
    try {
      await api.post("/auth/password/change", { current_password: v.current, new_password: v.password });
      form.reset();
      qc.invalidateQueries({ queryKey: qk.sessions });
      toast({ title: "Password changed", description: "Other sessions were signed out.", variant: "success" });
    } catch (e) {
      setPwError(e instanceof ApiError ? e.message : "Could not change password");
    }
  });

  return (
    <div className="stack stack-lg" style={{ maxWidth: 820 }}>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div>
          <h1>Account</h1>
          <p className="subtitle">{user?.email}</p>
        </div>
      </div>
      <section className="card card-pad stack" aria-labelledby="profile-h">
        <h2 id="profile-h">Profile</h2>
        <form
          className="row row-wrap"
          style={{ alignItems: "end" }}
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) saveName.mutate();
          }}
        >
          <div style={{ flex: 1, minWidth: 220 }}>
            <TextField label="Display name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
          </div>
          <Button type="submit" loading={saveName.isPending} disabled={!name.trim() || name === user?.display_name}>
            Save
          </Button>
        </form>
      </section>
      <section className="card card-pad stack" aria-labelledby="pw-h">
        <h2 id="pw-h">Change password</h2>
        <form className="stack" onSubmit={changePassword} noValidate style={{ maxWidth: 420 }}>
          {pwError && <div className="form-error" role="alert">{pwError}</div>}
          <TextField label="Current password" type="password" autoComplete="current-password" {...form.register("current")} error={form.formState.errors.current?.message} />
          <TextField label="New password" type="password" autoComplete="new-password" {...form.register("password")} error={form.formState.errors.password?.message} />
          <TextField label="Confirm new password" type="password" autoComplete="new-password" {...form.register("confirm")} error={form.formState.errors.confirm?.message} />
          <div>
            <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
              Change password
            </Button>
          </div>
        </form>
      </section>
      <section className="card" aria-labelledby="sessions-h">
        <div className="card-header">
          <h2 id="sessions-h">Active sessions</h2>
          <span className="spacer" />
          <Button
            size="sm"
            variant="danger"
            onClick={async () => {
              const ok = await confirm({
                title: "Sign out everywhere?",
                description: "All sessions, including this one, will be signed out.",
                confirmLabel: "Sign out everywhere",
                destructive: true,
              });
              if (!ok) return;
              await api.post("/auth/logout-all");
              setTokens(null);
              await logout();
              navigate("/login");
            }}
          >
            Sign out everywhere
          </Button>
        </div>
        {sessions.isLoading ? (
          <LoadingState />
        ) : sessions.error ? (
          <ErrorState error={sessions.error} onRetry={() => sessions.refetch()} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Device</th>
                  <th>IP address</th>
                  <th>Signed in</th>
                  <th>Last active</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sessions.data?.map((s) => (
                  <tr key={s.id}>
                    <td className="title-cell" title={s.user_agent ?? ""}>
                      {s.user_agent ?? "Unknown device"} {s.current && <Badge tone="success">this device</Badge>}
                    </td>
                    <td className="mono">{s.ip_address}</td>
                    <td>{formatDateTime(s.created_at)}</td>
                    <td>{relativeTime(s.last_used_at)}</td>
                    <td style={{ textAlign: "right" }}>
                      {!s.current && (
                        <Button size="sm" variant="ghost" onClick={() => revoke.mutate(s.id)}>
                          Revoke
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
