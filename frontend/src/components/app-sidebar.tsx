import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FileCode2,
  Calendar,
  Activity,
  Settings,
} from "lucide-react";
import { useAuth } from "@/auth/AuthProvider";
import { Brand } from "./brand";
import { cn } from "@/lib/utils";

const items = [
  { to: "/kindling/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/scripts", label: "Scripts", icon: FileCode2 },
  { to: "/schedules", label: "Schedules", icon: Calendar },
  { to: "/runs", label: "Runs", icon: Activity },
];

export function AppSidebar() {
  const { user } = useAuth();
  return (
    <aside className="hidden md:flex md:w-60 md:flex-col md:border-r md:bg-sidebar md:text-sidebar-foreground">
      <div className="flex h-14 items-center border-b border-sidebar-border px-4">
        <Brand />
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {items.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              )
            }
          >
            <it.icon className="h-4 w-4" />
            {it.label}
          </NavLink>
        ))}
        {user?.role === "admin" && (
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              )
            }
          >
            <Settings className="h-4 w-4" />
            Settings
          </NavLink>
        )}
      </nav>
    </aside>
  );
}
