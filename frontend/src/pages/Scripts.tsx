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

export function Scripts() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data: scripts = [] } = useQuery({
    queryKey: ["scripts"],
    queryFn: () => api<unknown[]>("/api/scripts"),
  });
  const run = useMutation({
    mutationFn: (id: string) => api(`/api/scripts/${id}/run`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => toast.success("Run started"),
    onError: (e: Error) => toast.error(e.message),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/api/scripts/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Script deleted");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Scripts</h1>
          <Button onClick={() => nav("/scripts/new")}>
            <Plus className="mr-2 h-4 w-4" /> New script
          </Button>
        </div>
        <Card>
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
                <TableRow key={s.id}>
                  <TableCell>
                    <Link
                      to={`/scripts/${s.id}`}
                      className="font-medium hover:underline"
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
                      onClick={() => run.mutate(s.id)}
                    >
                      Run
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => nav(`/scripts/${s.id}`)}
                    >
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => del.mutate(s.id)}
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
        </Card>
      </div>
    </AppShell>
  );
}
