import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { createScript, listScripts, deleteScript } from "@/api/scripts";

export function Scripts() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data: scripts, isLoading } = useQuery({
    queryKey: ["scripts"],
    queryFn: listScripts,
  });
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState<"python" | "node">("python");
  const [source, setSource] = useState("print('hello')\n");

  const create = useMutation({
    mutationFn: createScript,
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      setShowNew(false);
      nav(`/scripts/${s.id}`);
    },
  });

  const remove = useMutation({
    mutationFn: deleteScript,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scripts"] }),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Scripts</h1>
          <button
            onClick={() => setShowNew(true)}
            className="rounded bg-primary px-4 py-2 text-primary-foreground"
          >
            New script
          </button>
        </div>

        {isLoading ? (
          <div className="text-muted-foreground">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b text-left text-muted-foreground">
              <tr>
                <th className="py-2">Name</th>
                <th>Language</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {scripts?.map((s) => (
                <tr key={s.id} className="border-b">
                  <td className="py-3">
                    <Link to={`/scripts/${s.id}`} className="font-medium hover:underline">
                      {s.name}
                    </Link>
                  </td>
                  <td>{s.language}</td>
                  <td className="text-right">
                    <button
                      onClick={() => {
                        if (confirm(`Delete ${s.name}?`)) remove.mutate(s.id);
                      }}
                      className="text-xs text-destructive"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {showNew && (
          <div className="fixed inset-0 flex items-center justify-center bg-black/50">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate({ name, language, source });
              }}
              className="w-[500px] rounded-lg bg-background p-6 shadow"
            >
              <h2 className="mb-4 text-lg font-semibold">New script</h2>
              <label className="mb-1 block text-sm">Name</label>
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="mb-3 w-full rounded border px-3 py-2"
              />
              <label className="mb-1 block text-sm">Language</label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value as "python" | "node")}
                className="mb-3 w-full rounded border px-3 py-2"
              >
                <option value="python">Python</option>
                <option value="node">Node</option>
              </select>
              <label className="mb-1 block text-sm">Source</label>
              <textarea
                value={source}
                onChange={(e) => setSource(e.target.value)}
                rows={8}
                className="mb-4 w-full rounded border px-3 py-2 font-mono text-sm"
              />
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setShowNew(false)}>
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={create.isPending}
                  className="rounded bg-primary px-4 py-2 text-primary-foreground"
                >
                  Create
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </AppShell>
  );
}