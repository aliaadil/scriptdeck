import { Link } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";

/**
 * Explicit 404 page rendered for any unknown client-side route.
 *
 * This replaces the previous catch-all that silently redirected every
 * unmatched path to /kindling/dashboard, which was hiding in-app navigation
 * bugs (wrong root paths) by absorbing them into the dashboard.
 */
export function NotFound() {
  return (
    <AppShell>
      <div className="mx-auto max-w-md space-y-4 p-12 text-center">
        <h1 className="text-3xl font-semibold">404 — Not found</h1>
        <p className="text-sm text-muted-foreground">
          That route doesn't exist. If you arrived here from a link inside the
          app, that's a bug — please report it.
        </p>
        <div className="flex justify-center gap-2">
          <Button asChild>
            <Link to="/kindling/dashboard">Go to dashboard</Link>
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
