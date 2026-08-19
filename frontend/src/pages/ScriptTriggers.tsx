import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Copy, Plus, RefreshCw, Trash2, Webhook } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { toast } from "@/components/ui/sonner";
import { Field, FieldLabel, FieldContent } from "@/components/ui/field";
import { api } from "@/api/client";
import { listSchedules, deleteSchedule, type Schedule } from "@/api/schedules";
import {
  createWebhookForScript,
  deleteWebhook,
  listWebhooksForScript,
  patchWebhook,
  regenerateWebhook,
  type Webhook as WebhookRow,
} from "@/api/webhooks";

type Script = {
  id: number;
  name: string;
  language: string;
};

type ScriptListResponse = Array<{ id: number | string; name: string; language: string }>;

function CopyableUrl({ url }: { url: string }) {
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success("URL copied");
    } catch {
      toast.error("Copy failed — select and copy manually");
    }
  };
  return (
    <div className="flex items-center gap-2">
      <code className="flex-1 truncate rounded bg-muted px-2 py-1 text-xs">{url}</code>
      <Button size="sm" variant="outline" onClick={onCopy}>
        <Copy className="h-3.5 w-3.5" />
        Copy
      </Button>
    </div>
  );
}

export function ScriptTriggers() {
  const params = useParams();
  const scriptId = Number(params.id);
  const qc = useQueryClient();

  const { data: script } = useQuery({
    queryKey: ["script", scriptId],
    queryFn: async (): Promise<Script | null> => {
      const list = await api<ScriptListResponse>("/scripts");
      const found = list.find((s) => Number(s.id) === scriptId);
      return found
        ? { id: Number(found.id), name: found.name, language: found.language }
        : null;
    },
    enabled: !Number.isNaN(scriptId),
  });

  const { data: schedules = [] } = useQuery({
    queryKey: ["schedules", scriptId],
    queryFn: () => listSchedules(scriptId),
    enabled: !Number.isNaN(scriptId),
  });

  const { data: webhooks = [] } = useQuery({
    queryKey: ["webhooks", scriptId],
    queryFn: () => listWebhooksForScript(scriptId),
    enabled: !Number.isNaN(scriptId),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["webhooks", scriptId] });
    qc.invalidateQueries({ queryKey: ["schedules", scriptId] });
  };

  const deleteScheduleMut = useMutation({
    mutationFn: (id: number) => deleteSchedule(id),
    onSuccess: invalidate,
    onError: (e: Error) => toast.error(e.message),
  });

  const toggleWebhook = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      patchWebhook(id, { enabled }),
    onSuccess: invalidate,
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteWebhookMut = useMutation({
    mutationFn: (id: number) => deleteWebhook(id),
    onSuccess: invalidate,
    onError: (e: Error) => toast.error(e.message),
  });

  const [creating, setCreating] = useState(false);
  const [justCreated, setJustCreated] = useState<{ url: string } | null>(null);

  const create = useMutation({
    mutationFn: () =>
      createWebhookForScript(scriptId, {
        script_id: scriptId,
        description: creating ? "" : null,
        enabled: true,
        params: {},
      }),
    onSuccess: (row) => {
      invalidate();
      setCreating(false);
      if (row.url) setJustCreated({ url: row.url });
      toast.success("Webhook created");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const [regenId, setRegenId] = useState<number | null>(null);
  const regenerate = useMutation({
    mutationFn: (id: number) => regenerateWebhook(id),
    onSuccess: (row) => {
      invalidate();
      setRegenId(null);
      if (row.url) setJustCreated({ url: row.url });
      toast.success("Webhook URL rotated");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Triggers</h1>
            <p className="text-sm text-muted-foreground">
              {script ? script.name : `Script #${scriptId}`} · schedule + webhook
              triggers, each with its own params
            </p>
          </div>
          <Button onClick={() => setCreating(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New webhook
          </Button>
        </header>

        <section className="space-y-3">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Schedules ({schedules.length})
          </h2>
          {schedules.length === 0 ? (
            <Card className="p-6 text-center text-sm text-muted-foreground">
              No schedules yet. Use the Schedules page to attach a cron cadence.
            </Card>
          ) : (
            <div className="grid gap-2">
              {schedules.map((s) => (
                <ScheduleRow
                  key={s.id}
                  row={s}
                  onDelete={(id) => deleteScheduleMut.mutate(id)}
                />
              ))}
            </div>
          )}
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Webhooks ({webhooks.length})
          </h2>
          {webhooks.length === 0 ? (
            <Card className="p-6 text-center text-sm text-muted-foreground">
              No webhook URLs yet. Create one to fire this script from anywhere
              with an HTTP POST.
            </Card>
          ) : (
            <div className="grid gap-2">
              {webhooks.map((w) => (
                <WebhookRow
                  key={w.id}
                  row={w}
                  onToggle={(enabled) =>
                    toggleWebhook.mutate({ id: w.id, enabled })
                  }
                  onRegenerate={() => setRegenId(w.id)}
                  onDelete={() => deleteWebhookMut.mutate(w.id)}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      <Dialog
        open={creating}
        onOpenChange={(open) => {
          setCreating(open);
          if (!open) setJustCreated(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New webhook</DialogTitle>
            <DialogDescription>
              Generates an unguessable URL. Any HTTP POST to that URL fires
              this script — no JWT, no Basic auth, the URL is the credential.
            </DialogDescription>
          </DialogHeader>
          {justCreated ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">URL (store it now — shown once)</p>
              <CopyableUrl url={justCreated.url} />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Default params: none. Edit the webhook to add per-run flags.
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreating(false)}>
              Close
            </Button>
            {!justCreated && (
              <Button onClick={() => create.mutate()} disabled={create.isPending}>
                {create.isPending ? "Creating…" : "Create"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={regenId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRegenId(null);
            setJustCreated(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rotate webhook URL</DialogTitle>
            <DialogDescription>
              The current URL stops working immediately. Use this if the URL
              leaked.
            </DialogDescription>
          </DialogHeader>
          {justCreated ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">New URL</p>
              <CopyableUrl url={justCreated.url} />
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setRegenId(null)}>
              Cancel
            </Button>
            {!justCreated && (
              <Button
                onClick={() => regenId !== null && regenerate.mutate(regenId)}
                disabled={regenerate.isPending}
              >
                {regenerate.isPending ? "Rotating…" : "Rotate"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}

function ScheduleRow({
  row,
  onDelete,
}: {
  row: Schedule;
  onDelete: (id: number) => void;
}) {
  const nextRun = useMemo(() => {
    try {
      return new Date(row.next_run_at).toLocaleString();
    } catch {
      return row.next_run_at;
    }
  }, [row.next_run_at]);
  return (
    <Card className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={row.enabled ? "default" : "secondary"}>
            {row.enabled ? "enabled" : "disabled"}
          </Badge>
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{row.expression}</code>
          <span className="text-xs text-muted-foreground">{row.kind}</span>
        </div>
        <p className="mt-1 truncate text-xs text-muted-foreground">
          next run {nextRun} · runs {row.run_count ?? 0}
        </p>
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={() => onDelete(row.id)}
        aria-label={`Delete schedule ${row.id}`}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </Card>
  );
}

function WebhookRow({
  row,
  onToggle,
  onRegenerate,
  onDelete,
}: {
  row: WebhookRow;
  onToggle: (enabled: boolean) => void;
  onRegenerate: () => void;
  onDelete: () => void;
}) {
  return (
    <Card className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Webhook className="h-4 w-4 text-muted-foreground" />
          <Badge variant={row.enabled ? "default" : "secondary"}>
            {row.enabled ? "active" : "disabled"}
          </Badge>
          <span className="font-mono text-xs text-muted-foreground">
            #{row.id}
          </span>
          <span className="text-xs text-muted-foreground">
            fired {row.fire_count}×{row.last_fired_at ? ` · last ${new Date(row.last_fired_at).toLocaleString()}` : ""}
          </span>
        </div>
        {row.description ? (
          <p className="mt-1 text-sm">{row.description}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Switch checked={row.enabled} onCheckedChange={onToggle} aria-label="Toggle webhook" />
        <Button size="sm" variant="outline" onClick={onRegenerate}>
          <RefreshCw className="h-3.5 w-3.5" />
          Rotate
        </Button>
        <Button size="sm" variant="outline" onClick={onDelete} aria-label="Delete webhook">
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </Card>
  );
}
