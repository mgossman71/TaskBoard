import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { Building2 } from "lucide-react";
import { useCreateOrg, useOrgs } from "@/lib/queries";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorState, LoadingState } from "@/components/ui/Feedback";
import { AuthCard } from "../auth/AuthPages";

export function RootRedirect() {
  const { data, isLoading, error, refetch } = useOrgs();
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data?.length) return <Navigate to="/orgs" replace />;
  let last: string | null = null;
  try {
    last = localStorage.getItem("fb-last-org");
  } catch {
    /* ignore */
  }
  const target = data.find((o) => o.id === last) ?? data[0];
  return <Navigate to={`/o/${target.id}/projects`} replace />;
}

export function OrgsPage() {
  const { data, isLoading } = useOrgs();
  const create = useCreateOrg();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) return setError("Organization name is required");
    try {
      const org = await create.mutateAsync(name.trim());
      navigate(`/o/${org.id}/projects`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create organization");
    }
  };

  return (
    <AuthCard
      title={data?.length ? "Your organizations" : "Create your organization"}
      subtitle={data?.length ? "Pick an organization or create a new one." : `Hi ${user?.display_name ?? ""}! Organizations hold your projects and team.`}
    >
      {isLoading ? (
        <LoadingState />
      ) : (
        <div className="stack stack-lg">
          {!!data?.length && (
            <nav className="nav" aria-label="Organizations">
              {data.map((o) => (
                <Link key={o.id} to={`/o/${o.id}/projects`} className="nav-link">
                  <Building2 size={16} />
                  <span>{o.name}</span>
                  <span className="spacer" />
                  <span className="badge">{o.role}</span>
                </Link>
              ))}
            </nav>
          )}
          <form className="stack" onSubmit={submit} noValidate>
            <TextField
              label="New organization name"
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
              error={error ?? undefined}
              placeholder="Acme Inc."
            />
            <Button type="submit" variant="primary" loading={create.isPending}>
              Create organization
            </Button>
          </form>
          <button className="btn btn-ghost btn-sm" onClick={() => logout()}>
            Sign out
          </button>
        </div>
      )}
    </AuthCard>
  );
}
