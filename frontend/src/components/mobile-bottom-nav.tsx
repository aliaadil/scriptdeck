import { NavLink } from "react-router-dom";
import { LayoutDashboard, FileCode2, Calendar, Activity } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

const items = [
  { to: "/kindling/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/kindling/scripts", label: "Scripts", icon: FileCode2 },
  { to: "/kindling/schedules", label: "Schedules", icon: Calendar },
  { to: "/kindling/runs", label: "Runs", icon: Activity },
];

export function MobileBottomNav() {
  const isMobile = useIsMobile();
  if (!isMobile) return null;
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t bg-background pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          className={({ isActive }) =>
            cn(
              "flex flex-col items-center justify-center gap-1 py-2 text-xs transition-colors",
              isActive
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-muted-foreground hover:text-foreground"
            )
          }
        >
          <it.icon className="h-5 w-5" />
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}
