import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router";
import * as DM from "@radix-ui/react-dropdown-menu";
import {
  BarChart3,
  Building2,
  ChevronsUpDown,
  FolderKanban,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Plus,
  Settings,
  Sun,
  UserRound,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { useOrgs, useProjects } from "@/lib/queries";
import { Avatar } from "../ui/Feedback";
import { Button } from "../ui/Button";

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const options: { v: ThemeChoice; label: string; icon: ReactNode }[] = [
    { v: "light", label: "Light", icon: <Sun size={16} /> },
    { v: "dark", label: "Dark", icon: <Moon size={16} /> },
    { v: "system", label: "System", icon: <Monitor size={16} /> },
  ];
  const current = options.find((o) => o.v === theme)!;
  return (
    <DM.Root>
      <DM.Trigger asChild>
        <Button variant="ghost" size="md" iconOnly aria-label={`Theme: ${current.label}`}>
          {current.icon}
        </Button>
      </DM.Trigger>
      <DM.Portal>
        <DM.Content className="menu" align="end" sideOffset={6}>
          {options.map((o) => (
            <DM.Item key={o.v} className="menu-item" onSelect={() => setTheme(o.v)}>
              {o.icon} {o.label} {theme === o.v && <span className="faint">✓</span>}
            </DM.Item>
          ))}
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;
  return (
    <DM.Root>
      <DM.Trigger asChild>
        <button className="btn btn-ghost btn-md" aria-label="Account menu" data-testid="user-menu">
          <Avatar name={user.display_name} size={26} />
          <span className="hide-mobile">{user.display_name}</span>
        </button>
      </DM.Trigger>
      <DM.Portal>
        <DM.Content className="menu" align="end" sideOffset={6}>
          <DM.Label className="menu-label">{user.email}</DM.Label>
          <DM.Item className="menu-item" onSelect={() => navigate("/account")}>
            <UserRound size={16} /> Account & sessions
          </DM.Item>
          <DM.Separator className="menu-sep" />
          <DM.Item
            className="menu-item"
            onSelect={async () => {
              await logout();
              navigate("/login");
            }}
          >
            <LogOut size={16} /> Sign out
          </DM.Item>
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

function OrgSwitcher({ orgId }: { orgId?: string }) {
  const { data: orgs } = useOrgs();
  const navigate = useNavigate();
  const current = orgs?.find((o) => o.id === orgId);
  return (
    <DM.Root>
      <DM.Trigger asChild>
        <button className="btn btn-secondary btn-md org-switch" data-testid="org-switcher">
          <span className="row" style={{ minWidth: 0 }}>
            <Building2 size={16} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{current?.name ?? "Select organization"}</span>
          </span>
          <ChevronsUpDown size={14} />
        </button>
      </DM.Trigger>
      <DM.Portal>
        <DM.Content className="menu" align="start" sideOffset={6}>
          <DM.Label className="menu-label">Organizations</DM.Label>
          {orgs?.map((o) => (
            <DM.Item key={o.id} className="menu-item" onSelect={() => navigate(`/o/${o.id}/projects`)}>
              {o.name} <span className="faint">· {o.role}</span>
            </DM.Item>
          ))}
          <DM.Separator className="menu-sep" />
          <DM.Item className="menu-item" onSelect={() => navigate("/orgs")}>
            <Plus size={16} /> Create or manage organizations
          </DM.Item>
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

function ProjectNav({ orgId }: { orgId: string }) {
  const { data } = useProjects(orgId);
  if (!data?.length) return null;
  return (
    <nav className="nav" aria-label="Projects">
      <div className="nav-title">Projects</div>
      {data.map((p) => (
        <NavLink key={p.id} to={`/o/${orgId}/p/${p.id}/board`} className="nav-link">
          <span className="key-pill">{p.key}</span>
          <span>{p.name}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const { orgId } = useParams();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    if (orgId) {
      try {
        localStorage.setItem("tb-last-org", orgId);
      } catch {
        /* ignore */
      }
    }
  }, [orgId]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {open && <div className="sidebar-backdrop" onClick={() => setOpen(false)} aria-hidden />}
      <aside className={`sidebar${open ? " open" : ""}`} aria-label="Sidebar">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden>
            T
          </span>
          TaskBoard
        </Link>
        <OrgSwitcher orgId={orgId} />
        {orgId && (
          <nav className="nav" aria-label="Organization">
            <NavLink to={`/o/${orgId}/projects`} end className="nav-link">
              <FolderKanban size={17} />
              <span>Projects</span>
            </NavLink>
            <NavLink to={`/o/${orgId}/dashboard`} className="nav-link">
              <BarChart3 size={17} />
              <span>Dashboard</span>
            </NavLink>
            <NavLink to={`/o/${orgId}/settings`} className="nav-link">
              <Settings size={17} />
              <span>Members & settings</span>
            </NavLink>
          </nav>
        )}
        {orgId && <ProjectNav orgId={orgId} />}
      </aside>
      <div className="main">
        <header className="topbar">
          <Button variant="ghost" iconOnly className="mobile-only" aria-label="Open navigation" onClick={() => setOpen(true)}>
            <Menu size={18} />
          </Button>
          <div className="spacer" />
          <ThemeToggle />
          <UserMenu />
        </header>
        <main id="main" className="content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
