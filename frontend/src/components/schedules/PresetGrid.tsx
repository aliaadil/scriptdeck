import { cn } from "@/lib/utils";
import type { SchedulePreset } from "@/api/schedulePresets";

export function PresetGrid({
  presets,
  selected,
  onSelect,
}: {
  presets: SchedulePreset[];
  selected: string | null;
  onSelect: (preset: SchedulePreset) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">
      {presets.map((p) => (
        <button
          key={p.id}
          type="button"
          aria-pressed={selected === p.id}
          onClick={() => onSelect(p)}
          className={cn(
            "rounded-lg border p-3 text-left transition",
            selected === p.id
              ? "border-primary bg-primary/10"
              : "border-border hover:border-primary/50",
          )}
        >
          <div className="font-medium">{p.label}</div>
          <code className="mt-1 block text-xs text-muted-foreground">{p.cron}</code>
        </button>
      ))}
    </div>
  );
}
