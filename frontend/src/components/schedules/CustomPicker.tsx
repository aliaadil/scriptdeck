import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

type Frequency = "minutes" | "hourly" | "daily" | "weekly";

const FREQUENCIES: { value: Frequency; label: string }[] = [
  { value: "minutes", label: "Every 15 min" },
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "On chosen days" },
];

// cron day-of-week is 0=Sunday..6=Saturday. Keep the label order Mon-first for
// readability but map through explicit cron numbers so the two never drift.
const DAYS: { label: string; cron: number }[] = [
  { label: "Mon", cron: 1 },
  { label: "Tue", cron: 2 },
  { label: "Wed", cron: 3 },
  { label: "Thu", cron: 4 },
  { label: "Fri", cron: 5 },
  { label: "Sat", cron: 6 },
  { label: "Sun", cron: 0 },
];

function parseCron(cron: string) {
  const [minute = "0", hour = "0", dom = "*", month = "*", dow = "*"] =
    cron.trim().split(/\s+/);
  return { minute, hour, dom, month, dow };
}

/** Classify an expression into one of the four editable shapes. */
function frequencyOf(cron: string): Frequency {
  const { minute, hour, dow } = parseCron(cron);
  if (minute.startsWith("*/")) return "minutes";
  if (hour === "*") return "hourly";
  if (dow !== "*") return "weekly";
  return "daily";
}

function selectedDays(dow: string): number[] {
  if (dow === "*") return [];
  return dow
    .split(",")
    .flatMap((part) => {
      // Presets may use ranges such as "1-5"; expand so the day chips reflect them.
      const range = part.match(/^(\d)-(\d)$/);
      if (range) {
        const [, a, b] = range;
        const lo = Number(a);
        const hi = Number(b);
        return Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
      }
      return Number.isNaN(Number(part)) ? [] : [Number(part)];
    })
    .sort((a, b) => a - b);
}

export function CustomPicker({
  cron,
  onCronChange,
}: {
  cron: string;
  onCronChange: (c: string) => void;
}) {
  const { minute, hour, dom, month, dow } = parseCron(cron);
  const frequency = frequencyOf(cron);
  const days = selectedDays(dow);

  // "HH:mm" for the time input. Hourly/minutes shapes have no meaningful hour.
  const timeValue = `${hour === "*" ? "00" : hour.padStart(2, "0")}:${
    minute.startsWith("*/") ? "00" : minute.padStart(2, "0")
  }`;

  // Minute-only value used by the hourly branch. Show "0" when the slot
  // is a "*/N" wildcard or "*" so the number input always has something
  // to render.
  const minuteOnlyValue = (() => {
    if (minute === "*" || minute.startsWith("*/")) return "0";
    return minute;
  })();

  const setFrequency = (next: Frequency) => {
    const hh = hour === "*" ? "9" : hour;
    const mm = minute.startsWith("*/") ? "0" : minute;
    if (next === "minutes") onCronChange("*/15 * * * *");
    else if (next === "hourly") onCronChange(`${mm} * * * *`);
    else if (next === "daily") onCronChange(`${mm} ${hh} ${dom} ${month} *`);
    else onCronChange(`${mm} ${hh} ${dom} ${month} ${days.length ? days.join(",") : "1"}`);
  };

  const setTime = (value: string) => {
    const [hh = "0", mm = "0"] = value.split(":");
    onCronChange(`${Number(mm)} ${Number(hh)} ${dom} ${month} ${dow}`);
  };

  const setMinuteOnly = (value: string) => {
    const n = Math.max(0, Math.min(59, Number(value) || 0));
    onCronChange(`${n} * * * *`);
  };

  const toggleDay = (cronDay: number) => {
    const next = days.includes(cronDay)
      ? days.filter((d) => d !== cronDay)
      : [...days, cronDay].sort((a, b) => a - b);
    const hh = hour === "*" ? "9" : hour;
    const mm = minute.startsWith("*/") ? "0" : minute;
    onCronChange(`${mm} ${hh} ${dom} ${month} ${next.length ? next.join(",") : "*"}`);
  };

  // The "At" control changes shape per frequency. Daily/weekly get a full
  // time picker; hourly gets a minute-only number; "minutes" has no
  // meaningful minute slot (it's governed by the "*/N" wildcard).
  const atControl = (() => {
    if (frequency === "hourly") {
      return (
        <Input
          id="cron-time"
          type="number"
          min={0}
          max={59}
          step={1}
          value={minuteOnlyValue}
          onChange={(e) => setMinuteOnly(e.target.value)}
          className="w-[90px]"
          aria-label="At minute"
        />
      );
    }
    if (frequency === "minutes") {
      return (
        <Input
          id="cron-time"
          type="time"
          value={timeValue}
          disabled
          className="w-[130px]"
          aria-label="At"
        />
      );
    }
    return (
      <Input
        id="cron-time"
        type="time"
        value={timeValue}
        onChange={(e) => setTime(e.target.value)}
        className="w-[130px]"
        aria-label="At"
      />
    );
  })();

  const atLabel =
    frequency === "hourly" ? "At minute" : "At";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">Repeats</label>
          <Select value={frequency} onValueChange={(v) => setFrequency(v as Frequency)}>
            <SelectTrigger className="w-[170px]" aria-label="Repeats">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FREQUENCIES.map((f) => (
                <SelectItem key={f.value} value={f.value}>
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="mb-1 block text-xs text-muted-foreground">On these days</label>
          <div className="flex gap-1">
            {DAYS.map((d) => {
              const active = days.includes(d.cron);
              return (
                <button
                  key={d.label}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleDay(d.cron)}
                  className={cn(
                    "rounded-md border px-2 py-1 text-xs",
                    active
                      ? "border-primary bg-primary/10"
                      : "border-border opacity-60 hover:opacity-100",
                  )}
                >
                  {d.label}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs text-muted-foreground" htmlFor="cron-time">
            {atLabel}
          </label>
          {atControl}
        </div>
      </div>

      <AdvancedCronSection cron={cron} onCronChange={onCronChange} />
    </div>
  );
}

/** Expandable raw-cron editor. Collapsed by default. */
function AdvancedCronSection({
  cron,
  onCronChange,
}: {
  cron: string;
  onCronChange: (c: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t pt-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ChevronDown
          className={cn(
            "h-3 w-3 transition-transform",
            open ? "rotate-0" : "-rotate-90",
          )}
        />
        <span className="font-medium">Advanced — edit cron directly</span>
      </button>
      {open && (
        <div className="mt-2 space-y-1">
          <Input
            type="text"
            value={cron}
            onChange={(e) => onCronChange(e.target.value)}
            placeholder="* * * * *"
            spellCheck={false}
            autoComplete="off"
            className="w-[260px] font-mono"
            aria-label="Raw cron expression"
          />
          <p className="text-[11px] text-muted-foreground">
            Saving here overrides the friendly form below until you reopen this picker.
          </p>
        </div>
      )}
    </div>
  );
}