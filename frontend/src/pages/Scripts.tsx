import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { toast } from "@/components/ui/sonner";
import { Plus } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";

type ScriptRow = {
  id: string | number;
  name: string;
  language?: string | null;
  schedule?: string | null;
  last_run?: string | { status?: string; ago?: string } | null;
};

export function Scripts() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data: scripts = [] } = useQuery({
    queryKey: ["scripts"],
    queryFn: () => api<unknown[]>("/scripts"),
  });
  const run = useMutation({
    mutationFn: (id: string) => api(`/scripts/${id}/run`, { method: "POST" }),
    onSuccess: () => toast.success("Run started"),
    onError: (e: Error) => toast.error(e.message),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/scripts/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Script deleted");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const isMobile = useIsMobile();

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Scripts</h1>
          <Button onClick={() => nav("/kindling/scripts/new")}>
            <Plus className="mr-2 h-4 w-4" /> New script
          </Button>
        </div>
        <Card>
          {isMobile ? (
            <div className="space-y-2">
              {scripts.length === 0 && (
                <div className="p-3 text-center text-muted-foreground">
                  No scripts.
                </div>
              )}
              {(scripts as ScriptRow[]).map((s) => (
                <Link
                  key={s.id}
                  to={`/kindling/scripts/${s.id}`}
                  className="flex items-center justify-between rounded-md border p-3 hover:bg-muted"
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">{s.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {s.last_run && typeof s.last_run === "object"
                        ? `last run: ${s.last_run.status ?? "—"} · ${s.last_run.ago ?? "—"}`
                        : s.last_run
                          ? new Date(s.last_run).toLocaleString()
                          : "never run"}
                    </div>
                  </div>
                  <Badge variant="secondary">{s.language ?? "—"}</Badge>
                </Link>
              ))}
            </div>
          ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Language</TableHead>
                <TableHead>Schedule</TableHead>
                <TableHead>Last run</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scripts.map((s: any) => (
                <TableRow
                  key={s.id}
                  className="cursor-pointer"
                  onClick={() => nav(`/kindling/scripts/${s.id}`)}
                >
                  <TableCell>
                    <Link
                      to={`/kindling/scripts/${s.id}`}
                      className="font-medium hover:underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {s.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{s.language}</Badge>
                  </TableCell>
                  <TableCell>{s.schedule ?? "—"}</TableCell>
                  <TableCell>
                    {s.last_run
                      ? new Date(s.last_run).toLocaleString()
                      : "—"}
                  </TableCell>
                  <TableCell className="text-right space-x-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => { e.stopPropagation(); run.mutate(s.id); }}
                    >
                      Run
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => { e.stopPropagation(); nav(`/kindling/scripts/${s.id}`); }}
                    >
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={(e) => { e.stopPropagation(); del.mutate(s.id); }}
                    >
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {scripts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Empty>
                      <EmptyHeader>
                        <EmptyTitle>No scripts yet</EmptyTitle>
                        <EmptyDescription>
                          Create your first script to get started.
                        </EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
