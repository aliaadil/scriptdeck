import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AppShell } from "@/components/AppShell";

export function Runs() {
  const nav = useNavigate();
  const [status, setStatus] = useState<string>("all");
  const { data: runs = [] } = useQuery({
    queryKey: ["runs", status],
    queryFn: () => api(status === "all" ? "/runs" : `/runs?status=${status}`),
  });
  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <h1 className="text-2xl font-semibold">Runs</h1>
        <div className="flex gap-3">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="success">Success</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
              <SelectItem value="running">Running</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Script</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Exit</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(runs as any[]).map((r: any) => (
                <TableRow key={r.id} onClick={() => nav(`/runs/${r.id}`)} className="cursor-pointer">
                  <TableCell className="font-mono text-xs">{r.id.slice(0, 8)}</TableCell>
                  <TableCell>{r.script_name}</TableCell>
                  <TableCell>
                    <Badge variant={r.status === "failed" ? "destructive" : r.status === "success" ? "default" : "secondary"}>
                      {r.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{new Date(r.started_at).toLocaleString()}</TableCell>
                  <TableCell>{r.duration}</TableCell>
                  <TableCell>{r.exit_code}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>
    </AppShell>
  );
}