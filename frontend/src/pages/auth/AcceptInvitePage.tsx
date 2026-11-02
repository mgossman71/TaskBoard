import { Link, useNavigate, useSearchParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { qk, useInvitationPreview } from "@/lib/queries";
import type { Org } from "@/lib/types";
import { AuthCard } from "./AuthPages";
import { Button } from "@/components/ui/Button";
import { LoadingState } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toast";

export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { status, user, logout } = useAuth();
  const preview = useInvitationPreview(token);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { toast } = useToast();
  const accept = useMutation({
    mutationFn: () => api.post<Org>("/invitations/accept", { token }),
    onSuccess: (org) => {
      qc.invalidateQueries({ queryKey: qk.orgs });
      toast({ title: `Welcome to ${org.name}`, variant: "success" });
      navigate(`/o/${org.id}/projects`, { replace: true });
    },
  });
  const next = encodeURIComponent(`/invite?token=${token}`);

  if (!token || preview.isError)
    return (
      <AuthCard title="Invitation unavailable" subtitle="This invitation link is invalid, expired, or has already been used.">
        <Link to="/">Go to ForgeBoard</Link>
      </AuthCard>
    );
  if (preview.isLoading || status === "loading") return <LoadingState />;
  const inv = preview.data!;
  const mismatch = user && user.email.toLowerCase() !== inv.email.toLowerCase();

  return (
    <AuthCard title={`Join ${inv.org_name}`} subtitle={`You've been invited as ${inv.role} (${inv.email}).`}>
      {status === "anonymous" ? (
        <div className="stack">
          <Link className="btn btn-primary btn-md" to={`/register?next=${next}&email=${encodeURIComponent(inv.email)}`}>
            Create an account to accept
          </Link>
          <Link className="btn btn-secondary btn-md" to={`/login?next=${next}`}>
            I already have an account
          </Link>
        </div>
      ) : mismatch ? (
        <div className="stack">
          <div className="form-error" role="alert">
            You're signed in as {user!.email}, but this invitation is for {inv.email}.
          </div>
          <Button onClick={() => logout()}>Sign out and switch account</Button>
        </div>
      ) : (
        <div className="stack">
          {accept.error && (
            <div className="form-error" role="alert">
              {accept.error instanceof ApiError ? accept.error.message : "Could not accept invitation"}
            </div>
          )}
          <Button variant="primary" onClick={() => accept.mutate()} loading={accept.isPending}>
            Accept invitation
          </Button>
        </div>
      )}
    </AuthCard>
  );
}
