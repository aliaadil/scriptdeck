import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { cancelRun, getRun, listRunGroup } from "@/api/runs";
import { useLiveLogs } from "@/hooks/useLiveLogs";
import { useAuth } from "@/auth/AuthProvider";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { AttemptList } from "@/components/runs/AttemptList";
import { LogViewer } from "@/components/runs/LogViewer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/sonner";

function formatDuration(started_at: string, ended_at: string | null): string {
  if (!ended_at) return "running";
  const secs = (new Date(ended_at).getTime() - new Date(started_at).getTime()) / 1000;
  if (!Number.isFinite(secs)) return "—";
  return `${secs.toFixed(1)}s`;
}

export function RunView() {
  const { id } = useParams();
  const runId = Number(id);
  const { user } = useAuth();

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: 5000,
  });

  const { events, ended } = useLiveLogs(Number.isFinite(runId) ? runId : null);

  // Sibling attempts in this run's retry chain. Only meaningful once the run
  // has loaded and reports a retry_group.
  const retryGroup = run?.retry_group ?? null;
  const { data: attempts = [] } = useQuery({
    queryKey: ["run-group", retryGroup],
    queryFn: () => listRunGroup(retryGroup as string),
    enabled: retryGroup !== null,
  });
  const liveText = events
    .filter((e) => e.kind === "line")
    .map((e) => (e as { kind: "line"; text: string }).text)
    .join("");

  // Fallback: if the SSE stream produced nothing (e.g. run already finished
  // before we subscribed), pull the recorded log once.
  const { data: fallbackText } = useQuery({
    queryKey: ["run-log", runId],
    queryFn: async () => {
      const r = await api<{ content: string }>(`/runs/${runId}/log`);
      return r.content;
    },
    enabled: Number.isFinite(runId) && liveText === "",
  });

  const output = liveText || fallbackText || "";
  const canCancel = run?.status === "running" && user?.role !== "viewer" && !ended;

  async function onCancel() {
    try {
      await cancelRun(runId);
      toast.success("Run cancelled");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
        <Card>
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
            <CardTitle>Run #{runId}</CardTitle>
            <div className="flex items-center gap-3">
              {run && <StatusBadge status={run.status} />}
              {canCancel && (
                <Button variant="destructive" size="sm" onClick={onCancel}>
                  Cancel
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 text-sm sm:grid-cols-3">
            <Field
              label="Started at"
              value={run ? new Date(run.started_at).toLocaleString() : "—"}
            />
            <Field
              label="Duration"
              value={run ? formatDuration(run.started_at, run.ended_at) : "—"}
            />
            <Field label="Exit code" value={run?.exit_code ?? "—"} />
          </CardContent>
        </Card>

        <AttemptList runs={attempts} currentRunId={runId} />

        <Tabs defaultValue="output">
          <TabsList className="flex-wrap">
            <TabsTrigger value="output">Output</TabsTrigger>
            <TabsTrigger value="config">Config</TabsTrigger>
            <TabsTrigger value="metadata">Metadata</TabsTrigger>
          </TabsList>
          <TabsContent value="output">
            <Card>
              <CardContent className="bg-muted p-4 font-mono text-xs">
                <LogViewer
                  className="max-h-[60vh] overflow-auto"
                  text={output || "No output."}
                />
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="config">
            <Card>
              <CardContent className="p-4 font-mono text-xs">
                <pre className="whitespace-pre-wrap">
                  {JSON.stringify(
                    { script_id: run?.script_id ?? null, schedule_id: run?.schedule_id ?? null },
                    null,
                    2,
                  )}
                </pre>
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="metadata">
            <Card>
              <CardContent className="p-4 font-mono text-xs">
                <pre className="whitespace-pre-wrap">{JSON.stringify(run ?? {}, null, 2)}</pre>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}
