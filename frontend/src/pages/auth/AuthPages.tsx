import { useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { emailSchema, loginSchema, registerSchema, resetSchema } from "@/lib/validation";
import { TextField } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";

export function AuthCard({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="auth-wrap">
      <div className="card auth-card">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            F
          </span>
          ForgeBoard
        </div>
        <h1>{title}</h1>
        {subtitle && <p className="muted" style={{ marginBottom: 20 }}>{subtitle}</p>}
        {children}
      </div>
    </div>
  );
}

function safeNext(next: string | null) {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [formError, setFormError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) });

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      await login(v.email, v.password);
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Unable to sign in");
    }
  });

  return (
    <AuthCard title="Sign in" subtitle="Welcome back. Sign in to continue to your boards.">
      <form className="stack" onSubmit={onSubmit} noValidate>
        {formError && (
          <div className="form-error" role="alert">
            {formError}
          </div>
        )}
        <TextField label="Email" type="email" autoComplete="email" {...register("email")} error={formState.errors.email?.message} />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          {...register("password")}
          error={formState.errors.password?.message}
        />
        <Button type="submit" variant="primary" loading={formState.isSubmitting}>
          Sign in
        </Button>
        <div className="row row-wrap" style={{ justifyContent: "space-between" }}>
          <Link to="/forgot-password">Forgot password?</Link>
          <Link to={`/register${params.get("next") ? `?next=${encodeURIComponent(params.get("next")!)}` : ""}`}>
            Create an account
          </Link>
        </div>
      </form>
    </AuthCard>
  );
}

export function RegisterPage() {
  const { register: signup } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [formError, setFormError] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError } = useForm<z.infer<typeof registerSchema>>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: params.get("email") ?? "" },
  });

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      await signup(v.email, v.password, v.display_name);
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (e) {
      if (e instanceof ApiError) {
        const fields = e.fieldErrors();
        let mapped = false;
        for (const f of ["email", "password", "display_name"] as const) {
          if (fields[f]) {
            setError(f, { message: fields[f] });
            mapped = true;
          }
        }
        if (!mapped) setFormError(e.message);
      } else setFormError("Unable to create account");
    }
  });

  return (
    <AuthCard title="Create your account" subtitle="Start planning with your team in minutes.">
      <form className="stack" onSubmit={onSubmit} noValidate>
        {formError && (
          <div className="form-error" role="alert">
            {formError}
          </div>
        )}
        <TextField label="Your name" autoComplete="name" {...register("display_name")} error={formState.errors.display_name?.message} />
        <TextField label="Email" type="email" autoComplete="email" {...register("email")} error={formState.errors.email?.message} />
        <TextField
          label="Password"
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters with three of: lowercase, uppercase, digits, symbols."
          {...register("password")}
          error={formState.errors.password?.message}
        />
        <TextField
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          {...register("confirm")}
          error={formState.errors.confirm?.message}
        />
        <Button type="submit" variant="primary" loading={formState.isSubmitting}>
          Create account
        </Button>
        <p className="muted">
          Already have an account? <Link to={`/login${params.get("next") ? `?next=${encodeURIComponent(params.get("next")!)}` : ""}`}>Sign in</Link>
        </p>
      </form>
    </AuthCard>
  );
}

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const schema = z.object({ email: emailSchema });
  const { register, handleSubmit, formState } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      await api.post("/auth/password/forgot", { email: v.email });
      setSent(true);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Request failed");
    }
  });
  return (
    <AuthCard title="Reset your password" subtitle="We'll email you a single-use link to choose a new password.">
      {sent ? (
        <div className="stack">
          <p role="status">If an account exists for that email, a reset link is on its way. The link expires in one hour.</p>
          <Link to="/login">Back to sign in</Link>
        </div>
      ) : (
        <form className="stack" onSubmit={onSubmit} noValidate>
          {formError && <div className="form-error" role="alert">{formError}</div>}
          <TextField label="Email" type="email" autoComplete="email" {...register("email")} error={formState.errors.email?.message} />
          <Button type="submit" variant="primary" loading={formState.isSubmitting}>
            Send reset link
          </Button>
          <Link to="/login">Back to sign in</Link>
        </form>
      )}
    </AuthCard>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [done, setDone] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof resetSchema>>({ resolver: zodResolver(resetSchema) });
  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      await api.post("/auth/password/reset", { token, new_password: v.password });
      setDone(true);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Reset failed");
    }
  });
  if (!token)
    return (
      <AuthCard title="Invalid link" subtitle="This password reset link is missing its token.">
        <Link to="/forgot-password">Request a new link</Link>
      </AuthCard>
    );
  return (
    <AuthCard title="Choose a new password" subtitle="All existing sessions will be signed out.">
      {done ? (
        <div className="stack">
          <p role="status">Your password has been changed.</p>
          <Link to="/login">Sign in with your new password</Link>
        </div>
      ) : (
        <form className="stack" onSubmit={onSubmit} noValidate>
          {formError && <div className="form-error" role="alert">{formError}</div>}
          <TextField label="New password" type="password" autoComplete="new-password" {...register("password")} error={formState.errors.password?.message} />
          <TextField label="Confirm new password" type="password" autoComplete="new-password" {...register("confirm")} error={formState.errors.confirm?.message} />
          <Button type="submit" variant="primary" loading={formState.isSubmitting}>
            Set new password
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
