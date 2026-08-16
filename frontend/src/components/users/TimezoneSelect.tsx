import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const COMMON_TZS = [
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "America/Chicago",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Tokyo",
];

export function TimezoneSelect({
  value,
  onChange,
  hint,
  disabled,
}: {
  value: string;
  onChange: (tz: string) => void;
  hint?: string;
  disabled?: boolean;
}) {
  // A saved timezone outside the curated list must still render, otherwise the
  // trigger would show an empty value and a save would silently change it.
  const options = COMMON_TZS.includes(value) ? COMMON_TZS : [value, ...COMMON_TZS];

  return (
    <div className="flex items-center gap-3">
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger className="w-[240px]" aria-label="Timezone">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((tz) => (
            <SelectItem key={tz} value={tz}>
              {tz}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}
