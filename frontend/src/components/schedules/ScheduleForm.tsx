import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CronExpressionParser } from "cron-parser";
import { Save } from "lucide-react";
import { TogglePill } from "./TogglePill";
import { PresetGrid } from "./PresetGrid";
import { CustomPicker } from "./CustomPicker";
import { SkipDatesPopover } from "./SkipDatesPopover";
import { TimezoneSelect } from "../users/TimezoneSelect";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listPresets, type SchedulePreset } from "@/api/schedulePresets";
import { listScripts } from "@/api/scripts";

type Mode = "preset" | "custom";

export type SchedulePayload = {
  script_id: number;
  kind: "cron";
  expression: string;
  enabled: boolean;
  timezone: string;
  blackout_dates: string[] | null;
  include_days: number[] | null;
  overlap_policy: "skip" | "queue" | "parallel";
  queue_max: number;
  retry_max: number;
  retry_backoff: number;
  // Issue #17: per-trigger params. Optional in the form so existing
  // callers keep working — undefined serialises to "no params" (defaults
  // to '{}' on the backend).
  params?: Record<string, string> | null;
};

const DEFAULT_CRON = "0 9 * * *";

/**
 * Compute the next few fire times locally so the preview needs no round-trip.
 *
 * Blackout dates are filtered client-side to mirror the backend's
 * `compute_next_run`, which skips any fire landing on a blacked-out date.
 */
function previewNextRuns(
  cron: string,
  tz: string,
  blackouts: string[],
  count = 5,
): string[] {
  try {
    const it = CronExpressionParser.parse(cron, { currentDate: new Date(), tz });
    const skip = new Set(blackouts);
    const out: string[] = [];
    // Bound the walk so a cron fully covered by blackouts cannot spin forever.
    for (let i = 0; i < 500 && out.length < count; i++) {
      const d = it.next().toDate();
      const localDate = d.toLocaleDateString("en-CA", { timeZone: tz });
      if (!skip.has(localDate)) out.push(d.toISOString());
    }
    return out;
  } catch {
    return [];
  }
}

export function ScheduleForm({
  scriptId,
  initial,
  defaultTimezone = "UTC",
  submitting = false,
  onSubmit,
  onCancel,
}: {
  scriptId?: number;
  initial?: Partial<SchedulePayload>;
  defaultTimezone?: string;
  submitting?: boolean;
  onSubmit: (p: SchedulePayload) => void;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<Mode>("preset");
  const [cron, setCron] = useState(initial?.expression ?? DEFAULT_CRON);
  const [tz, setTz] = useState(initial?.timezone ?? defaultTimezone);
  const [blackouts, setBlackouts] = useState<string[]>(initial?.blackout_dates ?? []);
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const [selectedScript, setSelectedScript] = useState<number | undefined>(
    scriptId ?? initial?.script_id,
  );

  const { data: presets = [] } = useQuery({
    queryKey: ["schedule-presets"],
    queryFn: listPresets,
  });

  // Only needed when the caller did not pin a script (e.g. the "New schedule"
  // dialog on the schedules list page).
  const { data: scripts = [] } = useQuery({
    queryKey: ["scripts"],
    queryFn: listScripts,
    enabled: scriptId === undefined,
  });

  // Keep the preset highlight in sync when the cron is edited elsewhere.
  useEffect(() => {
    const match = presets.find((p: SchedulePreset) => p.cron === cron);
    setSelectedPreset(match ? match.id : null);
  }, [cron, presets]);

  const nextRuns = useMemo(
    () => previewNextRuns(cron, tz, blackouts),
    [cron, tz, blackouts],
  );

  const canSubmit = selectedScript !== undefined && cron.trim() !== "" && !submitting;

  const submit = () => {
    if (selectedScript === undefined) return;
    onSubmit({
      script_id: selectedScript,
      kind: "cron",
      expression: cron,
      enabled: initial?.enabled ?? true,
      timezone: tz,
      blackout_dates: blackouts.length ? blackouts : null,
      include_days: null,
      overlap_policy: initial?.overlap_policy ?? "skip",
      queue_max: initial?.queue_max ?? 10,
      retry_max: initial?.retry_max ?? 0,
      retry_backoff: initial?.retry_backoff ?? 0,
    });
  };

  return (
    <div className="space-y-6">
      {scriptId === undefined && (
        <section>
          <label className="mb-2 block text-sm font-medium">Script</label>
          <Select
            value={selectedScript !== undefined ? String(selectedScript) : undefined}
            onValueChange={(v) => setSelectedScript(Number(v))}
          >
            <SelectTrigger className="w-[280px]" aria-label="Script">
              <SelectValue placeholder="Choose a script…" />
            </SelectTrigger>
            <SelectContent>
              {scripts.map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </section>
      )}

      <section>
        <TogglePill<Mode>
          options={[
            { value: "preset", label: "Quick start" },
            { value: "custom", label: "Custom" },
          ]}
          value={mode}
          onChange={setMode}
        />
        <div className="mt-4">
          {mode === "preset" ? (
            <PresetGrid
              presets={presets}
              selected={selectedPreset}
              onSelect={(p) => {
                setSelectedPreset(p.id);
                setCron(p.cron);
              }}
            />
          ) : (
            <CustomPicker cron={cron} onCronChange={setCron} />
          )}
        </div>
        {nextRuns.length > 0 && (
          <div className="mt-3 text-xs">
            <div className="mb-1 text-muted-foreground">Next {nextRuns.length}</div>
            <ul className="divide-y divide-border/60 rounded-md border font-mono">
              {nextRuns.map((r) => {
                const d = new Date(r);
                const weekday = d.toLocaleDateString(undefined, {
                  weekday: "short",
                  month: "short",
                  day: "numeric",
                  timeZone: tz,
                });
                const clock = d.toLocaleTimeString(undefined, {
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: false,
                  timeZone: tz,
                });
                return (
                  <li key={r} className="flex items-center justify-between px-2 py-1">
                    <time dateTime={r} className="text-foreground/90">{weekday}</time>
                    <span className="text-foreground">{clock}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>

      <section className="space-y-4 border-t pt-4">
        <div>
          <label className="mb-2 block text-sm font-medium">Skip dates</label>
          <SkipDatesPopover value={blackouts} onChange={setBlackouts} />
        </div>
        <div>
          <label className="mb-2 block text-sm font-medium">Timezone</label>
          <TimezoneSelect
            value={tz}
            onChange={setTz}
            hint="Defaults to your profile · change to override per-schedule"
          />
        </div>
      </section>

      <footer className="flex items-center justify-between border-t pt-4">
        <span className="text-xs text-muted-foreground">
          Cron: <code>{cron}</code> · {tz}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" type="button" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" disabled={!canSubmit} onClick={submit}>
            <Save className="mr-1 h-4 w-4" /> Save schedule
          </Button>
        </div>
      </footer>
    </div>
  );
}
