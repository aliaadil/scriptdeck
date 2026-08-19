import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { api } from "@/api/client";
import { useIsMobile } from "@/hooks/use-mobile";

type Run = {
  id: string;
  script_name: string;
  status: string;
  started_at: string;
  duration: string;
  exit_code?: number;
};

export function Dashboard() {
  const { data: scripts = [] } = useQuery({
    queryKey: ["scripts"],
    queryFn: () => api<unknown[]>("/scripts"),
  });
  const { data: runs = [] } = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs"),
  });
  const { data: schedules = [] } = useQuery({
    queryKey: ["schedules"],
    queryFn: () => api<unknown[]>("/schedules"),
  });

  const todayRuns = runs.filter((r) => isToday(r.started_at));
  const failures = runs.filter((r) => r.status === "failed").length;
  const failureRate = todayRuns.length
    ? Math.round((failures / todayRuns.length) * 100)
    : 0;

  const runRows = runs.slice(0, 8);
  const isMobile = useIsMobile();

  return (
    <AppShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard title="Total scripts" value={scripts.length} />
          <StatCard
            title="Active schedules"
            value={schedules.filter((s: any) => s.enabled).length}
          />
          <StatCard title="Runs today" value={todayRuns.length} />
          <StatCard title="Failure rate" value={`${failureRate}%`} />
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Recent runs</CardTitle>
          </CardHeader>
          <CardContent>
            {isMobile ? (
              <div className="space-y-2">
                {runRows.length === 0 && (
                  <div className="text-center text-muted-foreground">
                    No runs yet.
                  </div>
                )}
                {runRows.map((r: any) => (
                  <Link
                    key={r.id}
                    to={`/kindling/runs/${r.id}`}
                    className="flex items-center justify-between rounded-md border p-3 hover:bg-muted"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">{r.script_name}</div>
                      <div className="text-xs text-muted-foreground">
                        {new Date(r.started_at).toLocaleString()} · {r.duration}
                      </div>
                    </div>
                    <Badge
                      variant={
                        r.status === "failed"
                          ? "destructive"
                          : r.status === "success"
                            ? "success"
                            : "secondary"
                      }
                    >
                      {r.status}
                    </Badge>
                  </Link>
                ))}
              </div>
            ) : (
              <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Script</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runRows.map((r: any) => (
                  <TableRow key={r.id}>
                    <TableCell>{r.script_name}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          r.status === "failed"
                            ? "destructive"
                            : r.status === "success"
                              ? "success"
                              : "secondary"
                        }
                      >
                        {r.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {new Date(r.started_at).toLocaleString()}
                    </TableCell>
                    <TableCell>{r.duration}</TableCell>
                  </TableRow>
                ))}
                {runRows.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="text-center text-muted-foreground"
                    >
                      No runs yet.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function StatCard({ title, value }: { title: string; value: number | string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold">{value}</div>
      </CardContent>
    </Card>
  );
}

function isToday(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}
