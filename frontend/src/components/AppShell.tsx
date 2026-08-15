import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/scripts", label: "Scripts" },
  { to: "/schedules", label: "Schedules" },
  { to: "/runs", label: "Runs" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b bg-background px-6 py-3">
        <Link to="/dashboard" className="text-lg font-semibold">ScriptDeck</Link>
        <nav className="flex gap-6">
          {navItems.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                cn("text-sm", isActive ? "font-semibold" : "text-muted-foreground")
              }
            >
              {n.label}
            </NavLink>
          ))}
          {user?.role === "admin" && (
            <NavLink to="/settings" className="text-sm text-muted-foreground">
              Settings
            </NavLink>
          )}
        </nav>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted-foreground">{user?.email}</span>
          <button
            onClick={async () => { await logout(); nav("/login"); }}
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}