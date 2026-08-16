import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { Switch } from "@/components/ui/switch";
import { toast } from "@/components/ui/sonner";
import { Plus } from "lucide-react";

export function Schedules() {
  const qc = useQueryClient();
  const { data: schedules = [] } = useQuery({
    queryKey: ["schedules"],
    queryFn: () => api("/api/schedules"),
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api(`/api/schedules/${id}`, { method: "PUT", body: JSON.stringify({ enabled }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Schedules</h1>
          <Button>
            <Plus className="mr-2 h-4 w-4" /> New schedule
          </Button>
        </div>
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Cron</TableHead>
                <TableHead>Script</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead>Last run</TableHead>
                <TableHead>Next run</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(schedules as any[]).map((s: any) => (
                <TableRow key={s.id}>
                  <TableCell className="font-mono text-xs">{s.cron}</TableCell>
                  <TableCell>{s.script_name}</TableCell>
                  <TableCell>
                    <Switch
                      checked={s.enabled}
                      onCheckedChange={(v) => toggle.mutate({ id: s.id, enabled: v })}
                    />
                  </TableCell>
                  <TableCell>
                    {s.last_run ? new Date(s.last_run).toLocaleString() : "—"}
                  </TableCell>
                  <TableCell>
                    {s.next_run ? new Date(s.next_run).toLocaleString() : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>
    </AppShell>
  );
}
