import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  ScheduleForm,
  type SchedulePayload,
} from "@/components/schedules/ScheduleForm";

type ScheduleRow = {
  id: number;
  expression: string;
  script_id: number;
  enabled: boolean;
  next_run_at: string | null;
  timezone: string | null;
};

export function Schedules() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);

  const { data: schedules = [] } = useQuery({
    queryKey: ["schedules"],
    queryFn: () => api<ScheduleRow[]>("/api/schedules"),
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api(`/api/schedules/${id}/${enabled ? "enable" : "disable"}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
    onError: (e: Error) => toast.error(e.message),
  });

  const create = useMutation({
    mutationFn: (payload: SchedulePayload) =>
      api("/api/schedules", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      setOpen(false);
      toast.success("Schedule created");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Schedules</h1>
          <Button onClick={() => setOpen(true)}>
            <Plus className="mr-2 h-4 w-4" /> New schedule
          </Button>
        </div>
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Cron</TableHead>
                <TableHead>Script</TableHead>
                <TableHead>Timezone</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead>Next run</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schedules.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-mono text-xs">{s.expression}</TableCell>
                  <TableCell>#{s.script_id}</TableCell>
                  <TableCell>{s.timezone ?? "UTC"}</TableCell>
                  <TableCell>
                    <Switch
                      checked={s.enabled}
                      onCheckedChange={(v) => toggle.mutate({ id: s.id, enabled: v })}
                    />
                  </TableCell>
                  <TableCell>
                    {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>New schedule</DialogTitle>
          </DialogHeader>
          <ScheduleForm
            defaultTimezone={user?.timezone ?? "UTC"}
            submitting={create.isPending}
            onSubmit={(p) => create.mutate(p)}
            onCancel={() => setOpen(false)}
          />
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
