import type { ReactNode } from "react";
import { AlertTriangle, Inbox } from "lucide-react";
import clsx from "clsx";
import { initials } from "@/lib/format";
import { ApiError } from "@/lib/api";

export function Spinner({ size = 18, label }: { size?: number; label?: string }) {
  return (
    <span className="spinner" style={{ width: size, height: size }} role={label ? "status" : undefined} aria-label={label}>
      {label && <span className="sr-only">{label}</span>}
    </span>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <Spinner size={22} />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, children, action, icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="state state-empty">
      <div className="state-icon" aria-hidden>
        {icon ?? <Inbox size={28} />}
      </div>
      <h3>{title}</h3>
      {children && <p className="muted">{children}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return (
    <div className="state state-error" role="alert">
      <div className="state-icon" aria-hidden>
        <AlertTriangle size={28} />
      </div>
      <h3>{error instanceof ApiError && error.status === 404 ? "Not found" : "Couldn't load this"}</h3>
      <p className="muted">{message}</p>
      {onRetry && (
        <button className="btn btn-secondary btn-md" onClick={onRetry} type="button">
          Try again
        </button>
      )}
    </div>
  );
}

const AVATAR_HUES = [210, 260, 330, 20, 150, 190, 45, 290];

export function Avatar({ name, size = 28, title }: { name: string; size?: number; title?: string }) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const hue = AVATAR_HUES[h % AVATAR_HUES.length];
  return (
    <span
      className="avatar"
      title={title ?? name}
      style={{ width: size, height: size, fontSize: size * 0.4, background: `hsl(${hue} 60% 45%)` }}
      aria-label={title ?? name}
      role="img"
    >
      {initials(name)}
    </span>
  );
}

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: string; className?: string }) {
  return <span className={clsx("badge", `badge-${tone}`, className)}>{children}</span>;
}
