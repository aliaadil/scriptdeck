import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";

export function RunView() {
  const { id } = useParams();
  const { data: run } = useQuery({
    queryKey: ["run", id],
    queryFn: () => api<{
      id: string;
      script_name: string;
      status: string;
      started_at: string;
      duration: string;
      exit_code: number;
      output: string;
      config?: Record<string, unknown>;
      metadata?: Record<string, unknown>;
    }>(`/runs/${id}`),
  });
  if (!run) return <div>Loading…</div>;
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>{run.script_name}</CardTitle>
            <p className="text-sm text-muted-foreground">Run {run.id.slice(0, 8)}</p>
          </div>
          <Badge variant={run.status === "failed" ? "destructive" : run.status === "success" ? "default" : "secondary"}>
            {run.status}
          </Badge>
        </CardHeader>
        <CardContent className="grid gap-4 text-sm sm:grid-cols-3">
          <Field label="Started" value={new Date(run.started_at).toLocaleString()} />
          <Field label="Duration" value={run.duration} />
          <Field label="Exit code" value={run.exit_code} />
        </CardContent>
      </Card>
      <Tabs defaultValue="output">
        <TabsList>
          <TabsTrigger value="output">Output</TabsTrigger>
          <TabsTrigger value="config">Config</TabsTrigger>
          <TabsTrigger value="metadata">Metadata</TabsTrigger>
        </TabsList>
        <TabsContent value="output">
          <Card>
            <CardContent className="bg-muted p-4 font-mono text-xs">
              <pre className="whitespace-pre-wrap">{run.output || "No output."}</pre>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="config">
          <Card>
            <CardContent className="text-sm">{JSON.stringify(run.config ?? {}, null, 2)}</CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="metadata">
          <Card>
            <CardContent className="text-sm">{JSON.stringify(run.metadata ?? {}, null, 2)}</CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
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
