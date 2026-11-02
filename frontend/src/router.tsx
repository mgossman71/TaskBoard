import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "./lib/auth";
import { LoadingState } from "./components/ui/Feedback";
import { AppShell } from "./components/layout/AppShell";
import { LoginPage, RegisterPage, ForgotPasswordPage, ResetPasswordPage } from "./pages/auth/AuthPages";
import { AcceptInvitePage } from "./pages/auth/AcceptInvitePage";
import { OrgsPage, RootRedirect } from "./pages/org/OrgsPage";
import { ProjectsPage } from "./pages/org/ProjectsPage";
import { OrgSettingsPage } from "./pages/org/OrgSettingsPage";
import { AccountPage } from "./pages/AccountPage";
import { ProjectLayout } from "./pages/project/ProjectLayout";
import { BoardPage } from "./pages/project/BoardPage";
import { TaskListPage } from "./pages/project/TaskListPage";
import { DependenciesPage } from "./pages/project/DependenciesPage";
import { ActivityPage } from "./pages/project/ActivityPage";
import { ProjectSettingsPage } from "./pages/project/ProjectSettingsPage";
import { NotFoundPage } from "./pages/NotFoundPage";

const DashboardPage = lazy(() => import("./pages/org/DashboardPage").then((m) => ({ default: m.DashboardPage })));

function RequireAuth() {
  const { status } = useAuth();
  const loc = useLocation();
  if (status === "loading") return <LoadingState label="Signing you in…" />;
  if (status === "anonymous") {
    const next = encodeURIComponent(loc.pathname + loc.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <Outlet />;
}

function PublicOnly() {
  const { status } = useAuth();
  const loc = useLocation();
  if (status === "loading") return <LoadingState />;
  if (status === "authenticated") {
    const next = new URLSearchParams(loc.search).get("next");
    return <Navigate to={next && next.startsWith("/") && !next.startsWith("//") ? next : "/"} replace />;
  }
  return <Outlet />;
}

export const router = createBrowserRouter([
  {
    element: <PublicOnly />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
      { path: "/forgot-password", element: <ForgotPasswordPage /> },
    ],
  },
  { path: "/reset-password", element: <ResetPasswordPage /> },
  { path: "/invite", element: <AcceptInvitePage /> },
  {
    element: <RequireAuth />,
    children: [
      { path: "/", element: <RootRedirect /> },
      { path: "/orgs", element: <OrgsPage /> },
      {
        element: <AppShell />,
        children: [
          { path: "/account", element: <AccountPage /> },
          {
            path: "/o/:orgId",
            children: [
              { index: true, element: <Navigate to="projects" replace /> },
              { path: "projects", element: <ProjectsPage /> },
              { path: "dashboard", element: <Suspense fallback={<LoadingState />}><DashboardPage /></Suspense> },
              { path: "settings", element: <OrgSettingsPage /> },
              {
                path: "p/:projectId",
                element: <ProjectLayout />,
                children: [
                  { index: true, element: <Navigate to="board" replace /> },
                  { path: "board", element: <BoardPage /> },
                  { path: "list", element: <TaskListPage /> },
                  { path: "dependencies", element: <DependenciesPage /> },
                  { path: "activity", element: <ActivityPage /> },
                  { path: "settings", element: <ProjectSettingsPage /> },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);
