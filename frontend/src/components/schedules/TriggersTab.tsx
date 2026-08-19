import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RotateCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "@/components/ui/sonner";
import {
  createTrigger,
  deleteTrigger,
  listTriggers,
  updateTrigger,
  type CreateTriggerResponse,
  type Trigger,
  type TriggerKind,
} from "@/api/triggers";

type Draft = {
  kind: TriggerKind;
  expression: string;
  enabled: boolean;
  paramsText: string;
};

function defaultDraft(kind: TriggerKind): Draft {
  return {
    kind,
    expression: kind === "interval" ? "5m" : kind === "cron" ? "* * * * *" : "",
    enabled: true,
    paramsText: "",
  };
}

type ParamsParseResult =
  | { ok: true; value: Record<string, unknown> | null }
  | { ok: false };

function parseParamsText(text: string): ParamsParseResult {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: null };
  try {
    const parsed = JSON.parse(trimmed);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      !Array.isArray(parsed)
    ) {
      return { ok: true, value: parsed as Record<string, unknown> };
    }
    return { ok: false };
  } catch {
    return { ok: false };
  }
}

function paramsToText(p: Trigger["params_json"]): string {
  if (!p) return "";
  return JSON.stringify(p, null, 2);
}

export function TriggersTab({ scriptId }: { scriptId: number }) {
  const qc = useQueryClient();

  const { data: triggers = [], isLoading } = useQuery({
    queryKey: ["triggers", scriptId],
    queryFn: () => listTriggers(scriptId),
  });

  const grouped = useMemo(() => {
    const out: Record<TriggerKind, Trigger[]> = {
      cron: [],
      interval: [],
      webhook: [],
    };
    for (const t of triggers) {
      out[t.kind].push(t);
    }
    return out;
  }, [triggers]);

  return (
    <div className="space-y-4 p-4">
      <NewTriggerCard
        scriptId={scriptId}
        onCreated={() => qc.invalidateQueries({ queryKey: ["triggers", scriptId] })}
      />
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading triggers…</p>
      ) : (
        <TriggerSection
          scriptId={scriptId}
          title="Cron schedules"
          empty="No cron schedules yet."
          triggers={grouped.cron}
          onChanged={() => qc.invalidateQueries({ queryKey: ["triggers", scriptId] })}
        />
      )}
      <TriggerSection
        scriptId={scriptId}
        title="Interval schedules"
        empty="No interval schedules yet."
        triggers={grouped.interval}
        onChanged={() => qc.invalidateQueries({ queryKey: ["triggers", scriptId] })}
      />
      <TriggerSection
        scriptId={scriptId}
        title="Webhook triggers"
        empty="No webhook triggers yet."
        triggers={grouped.webhook}
        onChanged={() => qc.invalidateQueries({ queryKey: ["triggers", scriptId] })}
      />
    </div>
  );
}

function NewTriggerCard({
  scriptId,
  onCreated,
}: {
  scriptId: number;
  onCreated: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(defaultDraft("cron"));
  const [lastToken, setLastToken] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => {
      const parsed = parseParamsText(draft.paramsText);
      const body: Parameters<typeof createTrigger>[1] = {
        kind: draft.kind,
        enabled: draft.enabled,
      };
      if (draft.kind !== "webhook") {
        body.expression = draft.expression;
      }
      if (parsed.ok && parsed.value) {
        body.params_json = parsed.value;
      }
      return createTrigger(scriptId, body);
    },
    onSuccess: (resp: CreateTriggerResponse) => {
      if (resp.token) setLastToken(resp.token);
      onCreated();
      setDraft(defaultDraft(draft.kind));
      toast.success(
        resp.token
          ? "Webhook created — copy the URL below now; it won't be shown again."
          : "Trigger created."
      );
    },
    onError: (e: unknown) => {
      const msg = e instanceof Error ? e.message : "Failed to create trigger";
      toast.error(msg);
    },
  });

  const paramsError = !parseParamsText(draft.paramsText).ok;

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center gap-2">
          <Plus className="h-4 w-4" />
          <h3 className="text-base font-medium">New trigger</h3>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="space-y-1">
            <Label>Kind</Label>
            <Select
              value={draft.kind}
              onValueChange={(v) => setDraft(defaultDraft(v as TriggerKind))}
            >
              <SelectTrigger className="min-h-10">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="cron">cron</SelectItem>
                <SelectItem value="interval">interval</SelectItem>
                <SelectItem value="webhook">webhook</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {draft.kind !== "webhook" ? (
            <div className="space-y-1 md:col-span-2">
              <Label>Expression</Label>
              <Input
                value={draft.expression}
                onChange={(e) => setDraft({ ...draft, expression: e.target.value })}
                placeholder={draft.kind === "cron" ? "* * * * *" : "5m"}
                className="min-h-10"
              />
            </div>
          ) : (
            <div className="md:col-span-2" />
          )}
        </div>
        <div className="space-y-1">
          <Label>Params (JSON object, optional)</Label>
          <Textarea
            value={draft.paramsText}
            onChange={(e) => setDraft({ ...draft, paramsText: e.target.value })}
            placeholder='{"region": "us-east-1", "shard": 3}'
            rows={3}
            className="font-mono text-xs"
          />
          {paramsError ? (
            <p className="text-xs text-destructive">
              Params must be a valid JSON object.
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          <Switch
            checked={draft.enabled}
            onCheckedChange={(v) => setDraft({ ...draft, enabled: v })}
          />
          <span className="text-sm">Enabled</span>
          <Button
            onClick={() => create.mutate()}
            disabled={create.isPending || paramsError}
            className="ml-auto min-h-10"
          >
            {create.isPending ? "Creating…" : "Create trigger"}
          </Button>
        </div>
        {lastToken ? (
          <div className="rounded-md border bg-muted/40 p-3 text-xs">
            <p className="font-medium">Webhook URL (copy now — token won't be shown again):</p>
            <code className="mt-1 block break-all">
              {window.location.origin}/api/kindling/webhooks/{lastToken}
            </code>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => {
                navigator.clipboard.writeText(
                  `${window.location.origin}/api/kindling/webhooks/${lastToken}`
                );
                toast.success("Copied.");
              }}
            >
              Copy URL
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function TriggerSection({
  scriptId,
  title,
  empty,
  triggers,
  onChanged,
}: {
  scriptId: number;
  title: string;
  empty: string;
  triggers: Trigger[];
  onChanged: () => void;
}) {
  if (triggers.length === 0) {
    return (
      <Card>
        <CardContent className="space-y-2 p-4">
          <h3 className="text-base font-medium">{title}</h3>
          <p className="text-sm text-muted-foreground">{empty}</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <h3 className="text-base font-medium">{title}</h3>
        <div className="divide-y">
          {triggers.map((t) => (
            <TriggerRow
              key={t.id}
              scriptId={scriptId}
              trigger={t}
              onChanged={onChanged}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function TriggerRow({
  scriptId,
  trigger,
  onChanged,
}: {
  scriptId: number;
  trigger: Trigger;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>({
    kind: trigger.kind,
    expression: trigger.expression ?? "",
    enabled: trigger.enabled,
    paramsText: paramsToText(trigger.params_json),
  });
  const [rotate, setRotate] = useState(false);

  // Reset draft when the row reloads after a save.
  useEffect(() => {
    if (!editing) {
      setDraft({
        kind: trigger.kind,
        expression: trigger.expression ?? "",
        enabled: trigger.enabled,
        paramsText: paramsToText(trigger.params_json),
      });
    }
  }, [trigger, editing]);

  const update = useMutation({
    mutationFn: () => {
      const parsed = parseParamsText(draft.paramsText);
      const body: Parameters<typeof updateTrigger>[2] = {
        kind: draft.kind,
        enabled: draft.enabled,
        rotate_token: rotate && draft.kind === "webhook",
      };
      if (draft.kind !== "webhook") {
        body.expression = draft.expression;
      }
      if (parsed.ok && parsed.value) {
        body.params_json = parsed.value;
      }
      return updateTrigger(scriptId, trigger.id, body);
    },
    onSuccess: (resp) => {
      if (resp.token) {
        toast.success(
          "Token rotated — copy the new URL below; it won't be shown again."
        );
      } else {
        toast.success("Trigger updated.");
      }
      setEditing(false);
      setRotate(false);
      onChanged();
    },
    onError: (e: unknown) => {
      toast.error(e instanceof Error ? e.message : "Update failed");
    },
  });

  const del = useMutation({
    mutationFn: () => deleteTrigger(scriptId, trigger.id),
    onSuccess: () => {
      toast.success("Trigger deleted.");
      onChanged();
    },
    onError: (e: unknown) => {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    },
  });

  const paramsError = !parseParamsText(draft.paramsText).ok;

  return (
    <div className="space-y-2 py-3">
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 text-sm">
            <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-xs">
              {trigger.kind}
            </span>
            {trigger.kind === "webhook" ? (
              <span className="text-xs text-muted-foreground">
                POST to /api/kindling/webhooks/&lt;your-token&gt;
              </span>
            ) : (
              <span className="font-mono text-xs">
                {trigger.expression ?? "(none)"}
              </span>
            )}
            <span className="text-xs text-muted-foreground">
              {trigger.enabled ? "enabled" : "disabled"}
            </span>
            {trigger.next_run_at ? (
              <span className="text-xs text-muted-foreground">
                next: {trigger.next_run_at}
              </span>
            ) : null}
            <span className="text-xs text-muted-foreground">
              runs: {trigger.run_count}
            </span>
          </div>
          {trigger.params_json ? (
            <pre className="mt-1 rounded bg-muted/40 p-2 text-xs">
              {JSON.stringify(trigger.params_json, null, 2)}
            </pre>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditing(!editing)}
            className="min-h-8"
          >
            {editing ? "Cancel" : "Edit"}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              if (window.confirm("Delete this trigger?")) del.mutate();
            }}
            disabled={del.isPending}
            className="min-h-8"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      {editing ? (
        <div className="space-y-2 rounded-md border bg-muted/20 p-3">
          {trigger.kind !== "webhook" ? (
            <div className="space-y-1">
              <Label>Expression</Label>
              <Input
                value={draft.expression}
                onChange={(e) => setDraft({ ...draft, expression: e.target.value })}
                className="min-h-9"
              />
            </div>
          ) : null}
          <div className="space-y-1">
            <Label>Params (JSON object, optional)</Label>
            <Textarea
              value={draft.paramsText}
              onChange={(e) => setDraft({ ...draft, paramsText: e.target.value })}
              rows={3}
              className="font-mono text-xs"
            />
            {paramsError ? (
              <p className="text-xs text-destructive">
                Params must be a valid JSON object.
              </p>
            ) : null}
          </div>
          <div className="flex items-center gap-3">
            <Switch
              checked={draft.enabled}
              onCheckedChange={(v) => setDraft({ ...draft, enabled: v })}
            />
            <span className="text-sm">Enabled</span>
            {trigger.kind === "webhook" ? (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={rotate}
                  onChange={(e) => setRotate(e.target.checked)}
                />
                <RotateCw className="h-3.5 w-3.5" /> rotate token
              </label>
            ) : null}
            <Button
              size="sm"
              onClick={() => update.mutate()}
              disabled={update.isPending || paramsError}
              className="ml-auto min-h-9"
            >
              {update.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}