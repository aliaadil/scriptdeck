import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { listSchedules, createSchedule, deleteSchedule, enableSchedule, disableSchedule } from "@/api/schedules";
import { listScripts } from "@/api/scripts";

export function Schedules() {
  const qc = useQueryClient();
  const { data: schedules } = useQuery({ queryKey: ["schedules"], queryFn: () => listSchedules() });
  const { data: scripts } = useQuery({ queryKey: ["scripts"], queryFn: listScripts });
  const [scriptId, setScriptId] = useState<number | "">("");
  const [kind, setKind] = useState<"cron" | "interval">("interval");
  const [expression, setExpression] = useState("15m");

  const create = useMutation({
    mutationFn: () => createSchedule({
      script_id: Number(scriptId), kind, expression,
      enabled: true, retry_max: 0, retry_backoff: 0,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });

  const remove = useMutation({
    mutationFn: deleteSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const enable = useMutation({
    mutationFn: enableSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const disable = useMutation({
    mutationFn: disableSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="mb-4 text-2xl font-semibold">Schedules</h1>
        <form
          onSubmit={(e) => { e.preventDefault(); create.mutate(); }}
          className="mb-6 flex gap-2 rounded border p-3"
        >
          <select
            required
            value={scriptId}
            onChange={(e) => setScriptId(Number(e.target.value))}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="">script…</option>
            {scripts?.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as "cron" | "interval")}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="interval">interval</option>
            <option value="cron">cron</option>
          </select>
          <input
            required
            value={expression}
            onChange={(e) => setExpression(e.target.value)}
            placeholder="15m or */5 * * * *"
            className="flex-1 rounded border px-2 py-1 text-sm"
          />
          <button
            type="submit"
            disabled={!scriptId || create.isPending}
            className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
          >
            Create
          </button>
        </form>
        <table className="w-full text-sm">
          <thead className="border-b text-left text-muted-foreground">
            <tr>
              <th className="py-2">Script</th><th>Kind</th><th>Expression</th>
              <th>Next run</th><th>Enabled</th><th></th>
            </tr>
          </thead>
          <tbody>
            {schedules?.map((s) => (
              <tr key={s.id} className="border-b">
                <td className="py-2">{s.script_id}</td>
                <td>{s.kind}</td>
                <td className="font-mono">{s.expression}</td>
                <td className="text-muted-foreground">{s.next_run_at}</td>
                <td>{s.enabled ? "yes" : "no"}</td>
                <td className="space-x-2 text-right">
                  {s.enabled ? (
                    <button onClick={() => disable.mutate(s.id)} className="text-xs">disable</button>
                  ) : (
                    <button onClick={() => enable.mutate(s.id)} className="text-xs">enable</button>
                  )}
                  <button onClick={() => remove.mutate(s.id)} className="text-xs text-destructive">delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
