import { useState } from "react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { CalendarPlus, X } from "lucide-react";

/**
 * Format as YYYY-MM-DD from local calendar parts.
 *
 * `toISOString()` converts to UTC first, which rolls the date back a day for
 * any user behind UTC (a date picked as the 5th would be sent as the 4th).
 */
function toISODate(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function fromISODate(s: string): Date {
  // Parse as local midnight so it round-trips through toISODate unchanged.
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, (m ?? 1) - 1, d ?? 1);
}

export function SkipDatesPopover({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = value.map(fromISODate);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" type="button">
            <CalendarPlus className="mr-2 h-4 w-4" /> Pick dates
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto p-0">
          <DayPicker
            mode="multiple"
            selected={selected}
            onSelect={(days) => onChange((days ?? []).map(toISODate).sort())}
            disabled={{ before: new Date() }}
          />
        </PopoverContent>
      </Popover>
      {value.map((d) => (
        <span
          key={d}
          className="inline-flex items-center gap-1 rounded-md border border-destructive bg-destructive/10 px-2 py-1 text-xs"
        >
          {d}
          <button
            type="button"
            aria-label={`Remove ${d}`}
            onClick={() => onChange(value.filter((x) => x !== d))}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
    </div>
  );
}
