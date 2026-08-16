import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { cancelRun, getRun } from "@/api/runs";
import { useLiveLogs } from "@/hooks/useLiveLogs";
import { useAuth } from "@/auth/AuthProvider";

export function RunView() {
  const { id } = useParams();
  const runId = Number(id);
  const { user } = useAuth();
  const { data: run } = useQuery({
    queryKey: ["run", runId], queryFn: () => getRun(runId),
    refetchInterval: 5000,
  });
  const { events, ended } = useLiveLogs(runId);

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Run #{runId}</h1>
          {run && <StatusBadge status={run.status} />}
        </div>
        {run?.status === "running" && user?.role !== "viewer" && !ended && (
          <button
            onClick={() => cancelRun(runId)}
            className="mb-3 rounded border border-destructive px-3 py-1 text-sm text-destructive"
          >
            Cancel
          </button>
        )}
        <pre className="rounded-lg border bg-muted p-4 text-xs leading-relaxed">
          {events
            .filter((e) => e.kind === "line")
            .map((e) => (e as { kind: "line"; text: string }).text)
            .join("")}
        </pre>
      </div>
    </AppShell>
  );
}
