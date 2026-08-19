import { useEffect, useState } from "react";

function format(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const totalSec = Math.floor(ms / 1000);
  const d = Math.floor(totalSec / 86400);
  const h = Math.floor((totalSec % 86400) / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

type Props = {
  started_at: string;
  ended_at?: string | null;
  status: string;
};

export function RunningDuration({ started_at, ended_at, status }: Props) {
  const isRunning = status === "running";
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [isRunning]);

  const started = new Date(started_at).getTime();
  const elapsed = isRunning
    ? Date.now() - started
    : ended_at
      ? new Date(ended_at).getTime() - started
      : NaN;

  return <span className="font-mono tabular-nums">{format(elapsed)}</span>;
}
