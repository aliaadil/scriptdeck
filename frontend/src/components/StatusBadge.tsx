import { cn } from "@/lib/utils";

const colors: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-800",
  failure: "bg-red-100 text-red-800",
  error: "bg-orange-100 text-orange-800",
  running: "bg-blue-100 text-blue-800",
  cancelled: "bg-gray-100 text-gray-800",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-block rounded px-2 py-0.5 text-xs font-medium",
        colors[status] ?? "bg-gray-100 text-gray-800",
      )}
    >
      {status}
    </span>
  );
}