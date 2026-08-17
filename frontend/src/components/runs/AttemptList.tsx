import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";

export type AttemptRun = {
  id: number;
  attempt: number;
  status: string;
  started_at: string;
  ended_at: string | null;
  exit_code: number | null;
};

export function AttemptList({
  runs,
  currentRunId,
}: {
  runs: AttemptRun[];
  currentRunId?: number;
}) {
  const [open, setOpen] = useState(false);
  if (runs.length <= 1) return null;

  return (
    <div className="rounded-lg border p-3">
      <Button
        variant="ghost"
        size="sm"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-start"
      >
        {open ? (
          <ChevronDown className="mr-1 h-4 w-4" />
        ) : (
          <ChevronRight className="mr-1 h-4 w-4" />
        )}
        {runs.length} attempts
      </Button>
      {open && (
        <ul className="mt-2 space-y-2">
          {runs.map((r) => (
            <li key={r.id} className="flex items-center gap-3 text-sm">
              <span className="w-16 text-muted-foreground">#{r.attempt}</span>
              <StatusBadge status={r.status} />
              <span className="text-xs text-muted-foreground">
                exit={r.exit_code ?? "—"}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {new Date(r.started_at).toLocaleString()}
              </span>
              {r.id === currentRunId ? (
                <span className="text-xs font-medium">current</span>
              ) : (
                <Link to={`/runs/${r.id}`} className="text-xs underline">
                  view
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
