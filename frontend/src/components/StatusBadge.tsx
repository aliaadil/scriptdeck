import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type StatusVariant = "success" | "destructive" | "secondary" | "outline";

const variantByStatus: Record<string, StatusVariant> = {
  success: "success",
  failure: "destructive",
  error: "destructive",
  running: "secondary",
  cancelled: "outline",
};

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  return (
    <Badge variant={variantByStatus[status] ?? "outline"} className={cn(className)}>
      {status}
    </Badge>
  );
}