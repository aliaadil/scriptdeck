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
  DialogDescription,
  DialogFooter,
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
import { Pencil, Plus, Trash2 } from "lucide-react";
import {
  ScheduleForm,
  type SchedulePayload,
} from "@/components/schedules/ScheduleForm";
import { getSchedule } from "@/api/schedules";

type ScheduleRow = {
  id: number;
  expression: string;
  script_id: number;
  enabled: boolean;
  next_run_at: string | null;
  timezone: string | null;
  run_count: number;
};

type Mode =
  | { kind: "create" }
  | { kind: "edit"; row: ScheduleRow };

export function Schedules() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [mode, setMode] = useState<Mode | null>(null);
  const [deleting, setDeleting] = useState<ScheduleRow | null>(null);

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

  const invalidate = () => qc.invalidateQueries({ queryKey: ["schedules"] });

  const create = useMutation({
    mutationFn: (payload: SchedulePayload) =>
      api("/api/schedules", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => {
      invalidate();
      setMode(null);
      toast.success("Schedule created");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: SchedulePayload }) =>
      api(`/api/schedules/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: () => {
      invalidate();
      setMode(null);
      toast.success("Schedule updated");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: number) =>
      api(`/api/schedules/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      setDeleting(null);
      toast.success("Schedule deleted");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const isEditing = mode?.kind === "edit";
  const editingId = isEditing ? mode.row.id : null;

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Schedules</h1>
          <Button onClick={() => setMode({ kind: "create" })}>
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
                <TableHead>Runs</TableHead>
                <TableHead>Next run</TableHead>
                <TableHead className="w-24 text-right">Actions</TableHead>
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
                  <TableCell>{Number(s.run_count)}</TableCell>
                  <TableCell>
                    {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Edit schedule ${s.id}`}
                        onClick={() => setMode({ kind: "edit", row: s })}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete schedule ${s.id}`}
                        onClick={() => setDeleting(s)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>

      <Dialog open={mode !== null} onOpenChange={(o) => !o && setMode(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{isEditing ? "Edit schedule" : "New schedule"}</DialogTitle>
          </DialogHeader>
          {mode !== null && (
            <EditOrCreateForm
              key={editingId ?? "new"}
              row={isEditing ? mode.row : null}
              defaultTimezone={user?.timezone ?? "UTC"}
              submitting={create.isPending || update.isPending}
              onSubmit={(payload) =>
                isEditing
                  ? update.mutate({ id: mode.row.id, payload })
                  : create.mutate(payload)
              }
              onCancel={() => setMode(null)}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete schedule?</DialogTitle>
            <DialogDescription>
              This will permanently delete schedule #{deleting?.id} and its future runs.
              This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => deleting && remove.mutate(deleting.id)}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}

/**
 * The edit form needs the full schedule record (including blackout_dates,
 * overlap_policy, queue_max, retry_max, retry_backoff, etc.) to prefill
 * accurately. Fetch it once when editing.
 */
function EditOrCreateForm({
  row,
  defaultTimezone,
  submitting,
  onSubmit,
  onCancel,
}: {
  row: ScheduleRow | null;
  defaultTimezone: string;
  submitting: boolean;
  onSubmit: (p: SchedulePayload) => void;
  onCancel: () => void;
}) {
  const isEdit = row !== null;
  const { data: full, isLoading } = useQuery({
    queryKey: ["schedule", row?.id],
    queryFn: () => getSchedule(row!.id),
    enabled: isEdit && row !== null,
  });

  if (isEdit && isLoading) {
    return <div className="py-8 text-center text-sm text-muted-foreground">Loading…</div>;
  }

  const initial: Partial<SchedulePayload> | undefined = isEdit && full
    ? {
        script_id: full.script_id,
        kind: "cron",
        expression: full.expression,
        enabled: full.enabled,
        timezone: full.timezone ?? defaultTimezone,
        blackout_dates: full.blackout_dates ?? null,
        include_days: full.include_days ?? null,
        overlap_policy: (full.overlap_policy ?? "skip") as SchedulePayload["overlap_policy"],
        queue_max: full.queue_max ?? 10,
        retry_max: full.retry_max,
        retry_backoff: full.retry_backoff,
      }
    : undefined;

  return (
    <ScheduleForm
      scriptId={isEdit ? row!.script_id : undefined}
      initial={initial}
      defaultTimezone={defaultTimezone}
      submitting={submitting}
      onSubmit={onSubmit}
      onCancel={onCancel}
    />
  );
}
