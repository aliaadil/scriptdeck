import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/api/client";

type Stats = {
  total_scripts: number;
  total_runs_24h: number;
  success_rate_24h: number;
  running_now: number;
  recent_runs: Array<{ id: number; script_id: number; status: string; started_at: string }>;
};

export function Dashboard() {
  const { data } = useQuery({
    queryKey: ["stats"],
    queryFn: () => api<Stats>("/api/stats"),
    refetchInterval: 5000,
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="mb-6 text-2xl font-semibold">Dashboard</h1>
        <div className="mb-8 grid grid-cols-4 gap-4">
          <Card label="Scripts" value={data?.total_scripts ?? "—"} />
          <Card label="Runs (24h)" value={data?.total_runs_24h ?? "—"} />
          <Card label="Success rate (24h)" value={
            data ? `${Math.round(data.success_rate_24h * 100)}%` : "—"
          } />
          <Card label="Running now" value={data?.running_now ?? "—"} />
        </div>
        <h2 className="mb-3 text-lg font-semibold">Recent runs</h2>
        <table className="w-full text-sm">
          <tbody>
            {data?.recent_runs.map((r) => (
              <tr key={r.id} className="border-b">
                <td className="py-2">
                  <Link to={`/runs/${r.id}`} className="hover:underline">#{r.id}</Link>
                </td>
                <td>script {r.script_id}</td>
                <td><StatusBadge status={r.status} /></td>
                <td className="text-muted-foreground">{r.started_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}