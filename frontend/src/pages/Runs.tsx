import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { listRuns } from "@/api/runs";

export function Runs() {
  const [status, setStatus] = useState<string>("");
  const { data: runs } = useQuery({
    queryKey: ["runs", status],
    queryFn: () => listRuns(status ? { status } : undefined),
    refetchInterval: 5000,
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Runs</h1>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded border px-3 py-1 text-sm"
          >
            <option value="">all</option>
            <option value="running">running</option>
            <option value="success">success</option>
            <option value="failure">failure</option>
            <option value="error">error</option>
            <option value="cancelled">cancelled</option>
          </select>
        </div>
        <table className="w-full text-sm">
          <thead className="border-b text-left text-muted-foreground">
            <tr>
              <th className="py-2">ID</th><th>Script</th><th>Status</th><th>Started</th>
            </tr>
          </thead>
          <tbody>
            {runs?.map((r) => (
              <tr key={r.id} className="border-b">
                <td className="py-2">
                  <Link to={`/runs/${r.id}`} className="hover:underline">#{r.id}</Link>
                </td>
                <td>{r.script_id}</td>
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
