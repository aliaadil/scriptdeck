import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RotateCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
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
  type TriggerBody,
  type TriggerKind,
} from "@/api/triggers";
import { shlex } from "@/lib/shell";

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
  | { ok: true; argv: string[] | null }
  | { ok: false; error: string };

function parseParamsText(text: string): ParamsParseResult {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, argv: null };
  const r = shlex(trimmed);
  if (r.error) return { ok: false, error: r.error };
  return { ok: true, argv: r.tokens ?? [] };
}

function paramsToText(p: Trigger["params_json"]): string {
  // Read both shapes so legacy dict params (KINDLING_PARAM_<KEY>=value path)
  // and new argv lists both display in the same single-line format that
  // the input expects.
  if (Array.isArray(p)) return p.map(String).join(" ");
  if (p && typeof p === "object") {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(p as Record<string, unknown>)) {
      if (v === true || v === "true") parts.push(`--${k}`);
      else parts.push(`--${k} ${String(v)}`);
    }
    return parts.join(" ");
  }
  return "";
}

function paramsPreview(argv: string[] | null): string | null {
  if (!argv || argv.length === 0) return null;
  return `argv: ${argv.join(" ")}`;
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
      const body: TriggerBody = {
        kind: draft.kind,
        enabled: draft.enabled,
      };
      if (draft.kind !== "webhook") {
        body.expression = draft.expression;
      }
      if (parsed.ok && parsed.argv && parsed.argv.length > 0) {
        // Same argv shape as the Manual Run button: copy the value that
        // worked manually into the trigger and they execute identically.
        body.params_argv = parsed.argv;
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

  const parsedParams = parseParamsText(draft.paramsText);
  const paramsError = !parsedParams.ok ? parsedParams.error : null;
  const paramsArgv = parsedParams.ok ? parsedParams.argv : null;
  const paramsPreviewText = paramsPreview(paramsArgv);

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
          <Label>Params (optional)</Label>
          <Input
            data-testid="trigger-params-input"
            value={draft.paramsText}
            onChange={(e) => setDraft({ ...draft, paramsText: e.target.value })}
            placeholder="users -p 9000"
            aria-invalid={paramsError != null}
            className="min-h-10 font-mono text-xs"
          />
          {paramsPreviewText && !paramsError ? (
            <p
              className="truncate font-mono text-[11px] text-muted-foreground"
              data-testid="trigger-params-preview"
              title={paramsPreviewText}
            >
              {paramsPreviewText}
            </p>
          ) : null}
          {paramsError ? (
            <p
              className="text-xs text-destructive"
              role="alert"
              data-testid="trigger-params-error"
            >
              {paramsError}
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
            disabled={create.isPending || paramsError != null}
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
      const body: TriggerBody = {
        kind: draft.kind,
        enabled: draft.enabled,
        rotate_token: rotate && draft.kind === "webhook",
      };
      if (draft.kind !== "webhook") {
        body.expression = draft.expression;
      }
      if (parsed.ok && parsed.argv && parsed.argv.length > 0) {
        // Migrate legacy dict params over to argv on first save.
        body.params_argv = parsed.argv;
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

  const parsedParams = parseParamsText(draft.paramsText);
  const paramsError = !parsedParams.ok ? parsedParams.error : null;
  const paramsArgv = parsedParams.ok ? parsedParams.argv : null;
  const paramsPreviewText = paramsPreview(paramsArgv);

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
            <pre className="mt-1 truncate rounded bg-muted/40 p-2 font-mono text-xs">
              {paramsToText(trigger.params_json) || JSON.stringify(trigger.params_json, null, 2)}
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
            <Label>Params (optional)</Label>
            <Input
              data-testid="trigger-params-input"
              value={draft.paramsText}
              onChange={(e) => setDraft({ ...draft, paramsText: e.target.value })}
              placeholder="users -p 9000"
              aria-invalid={paramsError != null}
              className="min-h-9 font-mono text-xs"
            />
            {paramsPreviewText && !paramsError ? (
              <p
                className="truncate font-mono text-[11px] text-muted-foreground"
                data-testid="trigger-params-preview"
                title={paramsPreviewText}
              >
                {paramsPreviewText}
              </p>
            ) : null}
            {paramsError ? (
              <p
                className="text-xs text-destructive"
                role="alert"
                data-testid="trigger-params-error"
              >
                {paramsError}
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
              disabled={update.isPending || paramsError != null}
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