import { Link } from "react-router";
import { AuthCard } from "./auth/AuthPages";

export function NotFoundPage() {
  return (
    <AuthCard title="Page not found" subtitle="The page you're looking for doesn't exist or you don't have access to it.">
      <Link to="/">Go to TaskBoard</Link>
    </AuthCard>
  );
}
