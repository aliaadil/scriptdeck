import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ApiError, api } from "@/api/client";
import { cancelRun } from "@/api/runs";
import { listSchedules, type Schedule } from "@/api/schedules";
import { useAuth } from "@/auth/AuthProvider";
import { AppShell } from "@/components/AppShell";
import {
  Card,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { toast } from "@/components/ui/sonner";
import { RunningDuration } from "@/components/runs/RunningDuration";
import { useIsMobile } from "@/hooks/use-mobile";
import { X } from "lucide-react";

function StartedCell({ iso }: { iso: string }) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return <span>{iso}</span>;
  const utc = d.toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
  const local = d.toLocaleString();
  return (
    <span title={`UTC: ${utc}`} className="font-mono text-xs">
      <span>{local}</span>
      <span className="block text-[10px] text-muted-foreground">
        UTC {utc}
      </span>
    </span>
  );
}

function StatusBadge({ status, skip_reason }: { status: string; skip_reason?: string | null }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <Badge variant={variantFor(status)}>{status}</Badge>
      {skip_reason && (
        <span
          title={skip_reason}
          className="max-w-[16ch] truncate text-[10px] text-muted-foreground"
        >
          {skip_reason}
        </span>
      )}
    </div>
  );
}

function ScheduleCell({ id, timezone }: { id: number | null; timezone?: string | null }) {
  if (!id) return <span>—</span>;
  return (
    <div className="flex flex-col items-start">
      <span className="font-mono text-xs">#{id}</span>
      {timezone && (
        <span className="text-[10px] text-muted-foreground">{timezone}</span>
      )}
    </div>
  );
}

const STATUSES = [
  "all",
  "running",
  "success",
  "failed",
  "cancelled",
  "error",
  "skipped",
] as const;
type Status = (typeof STATUSES)[number];
const PAGE_SIZE = 20;

type RunRow = {
  id: number;
  script_id: number;
  script_name: string;
  schedule_id: number | null;
  schedule_timezone?: string | null;
  started_at: string;
  ended_at: string | null;
  exit_code: number | null;
  status: string;
  skip_reason?: string | null;
};

function runsUrl(opts: {
  schedule?: string;
  status?: Status;
  offset?: number;
  limit?: number;
}) {
  const params = new URLSearchParams();
  if (opts.schedule && opts.schedule !== "all")
    params.set("schedule_id", opts.schedule);
  if (opts.status && opts.status !== "all")
    params.set(
      "status",
      opts.status === "failed" ? "failure" : opts.status,
    );
  if (opts.offset && opts.offset > 0)
    params.set("offset", String(opts.offset));
  // limit is always set below so the URL always carries a query string.
  params.set("limit", String(opts.limit ?? PAGE_SIZE));
  return `/runs?${params.toString()}`;
}

function variantFor(
  status: string,
): "default" | "secondary" | "destructive" | "success" {
  switch (status) {
    case "success":
      return "success";
    case "failure":
    case "error":
      return "destructive";
    default:
      return "secondary";
  }
}

export function Runs() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { user } = useAuth();
  const [schedule, setSchedule] = useState("all");
  const [status, setStatus] = useState<Status>("all");
  const [page, setPage] = useState(1);

  const { data: schedules = [] } = useQuery<Schedule[]>({
    queryKey: ["schedules-for-runs"],
    queryFn: () => listSchedules(),
  });

  const offset = (page - 1) * PAGE_SIZE;
  const commonArgs = { schedule, status, limit: PAGE_SIZE };

  const history = useQuery({
    queryKey: ["runs-history", schedule, status, page],
    queryFn: () => api<RunRow[]>(runsUrl({ ...commonArgs, offset })),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
    placeholderData: keepPreviousData,
  });

  // Always queries status=running; the schedule filter alone changes behavior.
  const running = useQuery({
    queryKey: ["runs-running", schedule],
    queryFn: () =>
      api<RunRow[]>(
        runsUrl({ schedule, status: "running", limit: 100 }),
      ),
    refetchInterval: (q) =>
      q.state.data && (q.state.data as unknown[]).length > 0
        ? 2000
        : false,
    refetchIntervalInBackground: false,
  });

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["runs-history"] });
    qc.invalidateQueries({ queryKey: ["runs-running"] });
  }

  async function onCancel(id: number) {
    try {
      await cancelRun(id);
      toast.success("Run cancelled");
      invalidate();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) toast.error("Already finished");
      else toast.error((e as Error).message);
      invalidate();
    }
  }

  const showRunning = (running.data?.length ?? 0) > 0;
  const noMatches =
    !showRunning &&
    (history.data?.length ?? 0) === 0 &&
    !history.isLoading;

  const isMobile = useIsMobile();
  const historyRows = history.data ?? [];

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <h1 className="text-2xl font-semibold">Runs</h1>
        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={schedule}
            onValueChange={(v) => {
              setSchedule(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="All schedules" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All schedules</SelectItem>
              {schedules.map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  #{s.id} · {s.expression}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={status}
            onValueChange={(v) => {
              setStatus(v as Status);
              setPage(1);
            }}
          >
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {showRunning && (
          <Card>
            <CardHeader className="px-4 py-3">
              <CardTitle className="text-sm font-medium">
                Currently running ({running.data?.length ?? 0})
              </CardTitle>
            </CardHeader>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Script</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead className="w-24 text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(running.data ?? []).map((r) => (
                  <TableRow
                    key={r.id}
                    tabIndex={0}
                    onClick={() => nav(`/kindling/runs/${r.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter")
                        nav(`/kindling/runs/${r.id}`);
                    }}
                    className="cursor-pointer hover:bg-muted/50"
                  >
                    <TableCell className="font-mono text-xs">
                      #{String(r.id).slice(0, 6)}
                    </TableCell>
                    <TableCell>{r.script_name}</TableCell>
                    <TableCell>
                      <StatusBadge status={r.status} skip_reason={r.skip_reason} />
                    </TableCell>
                    <TableCell>
                      <StartedCell iso={r.started_at} />
                    </TableCell>
                    <TableCell>
                      <RunningDuration
                        started_at={r.started_at}
                        ended_at={r.ended_at}
                        status={r.status}
                      />
                    </TableCell>
                    <TableCell>{r.exit_code ?? "—"}</TableCell>
                    <TableCell className="text-right">
                      {user?.role !== "viewer" && r.status === "running" && (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Cancel run ${r.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onCancel(r.id);
                          }}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}

        <Card>
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm font-medium">History</CardTitle>
          </CardHeader>
          {isMobile ? (
            <div className="space-y-2 p-3">
              {historyRows.length === 0 && (
                <div className="text-center text-muted-foreground">No runs yet.</div>
              )}
              {historyRows.map((r: any) => (
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
                  <Badge variant={r.status === "failed" ? "destructive" : r.status === "success" ? "success" : "secondary"}>
                    {r.status}
                  </Badge>
                </Link>
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Script</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead>Schedule</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(history.data ?? []).map((r) => (
                  <TableRow
                    key={r.id}
                    tabIndex={0}
                    onClick={() => nav(`/kindling/runs/${r.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") nav(`/kindling/runs/${r.id}`);
                    }}
                    className="cursor-pointer hover:bg-muted/50"
                  >
                    <TableCell className="font-mono text-xs">
                      #{String(r.id).slice(0, 6)}
                    </TableCell>
                    <TableCell>{r.script_name}</TableCell>
                    <TableCell>
                      <StatusBadge status={r.status} skip_reason={r.skip_reason} />
                    </TableCell>
                    <TableCell>
                      <StartedCell iso={r.started_at} />
                    </TableCell>
                    <TableCell>
                      <RunningDuration
                        started_at={r.started_at}
                        ended_at={r.ended_at}
                        status={r.status}
                      />
                    </TableCell>
                    <TableCell>{r.exit_code ?? "—"}</TableCell>
                    <TableCell>
                      <ScheduleCell id={r.schedule_id} timezone={r.schedule_timezone} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>

        {noMatches && (
          <div className="py-12 text-center text-sm text-muted-foreground">
            No runs match these filters.
          </div>
        )}

        <Pagination>
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  setPage((p) => Math.max(1, p - 1));
                }}
                aria-disabled={page === 1}
              />
            </PaginationItem>
            <PaginationItem className="px-4 text-sm">
              page {page}
            </PaginationItem>
            <PaginationItem>
              <PaginationNext
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  setPage((p) => p + 1);
                }}
                aria-disabled={(history.data?.length ?? 0) < PAGE_SIZE}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </div>
    </AppShell>
  );
}
