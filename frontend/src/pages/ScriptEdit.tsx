import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, lazy, Suspense } from "react";
import { useParams } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { getScript, updateScript } from "@/api/scripts";
import { detectDeps, getDeps, setDeps } from "@/api/deps";
import { deleteEnv, getEnv, setEnv } from "@/api/envs";

const MonacoEditor = lazy(() =>
  import("@monaco-editor/react").then((m) => ({ default: m.default })),
);

type Tab = "source" | "deps" | "env";

export function ScriptEdit() {
  const { id } = useParams();
  const scriptId = Number(id);
  const [tab, setTab] = useState<Tab>("source");

  const { data: script } = useQuery({
    queryKey: ["script", scriptId],
    queryFn: () => getScript(scriptId),
  });

  if (!script) {
    return <AppShell><div className="p-8">Loading…</div></AppShell>;
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="mb-4 text-2xl font-semibold">{script.name}</h1>
        <div className="mb-4 flex gap-2 border-b">
          {(["source", "deps", "env"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm ${
                tab === t ? "border-b-2 border-primary font-semibold" : "text-muted-foreground"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        {tab === "source" && <SourceTab scriptId={scriptId} language={script.language} />}
        {tab === "deps" && <DepsTab scriptId={scriptId} />}
        {tab === "env" && <EnvTab scriptId={scriptId} />}
      </div>
    </AppShell>
  );
}

function SourceTab({ scriptId, language }: { scriptId: number; language: string }) {
  const [code, setCode] = useState("");
  const [saving, setSaving] = useState(false);

  // fetch full source on mount
  useQuery({
    queryKey: ["script-source", scriptId],
    enabled: !!scriptId && !Number.isNaN(scriptId),
    queryFn: async () => {
      // raw fetch because /source returns plain text, not JSON
      const text = await (await fetch(`/api/scripts/${scriptId}/source`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("scriptdeck_token")}` },
      })).text();
      setCode(text);
      return text;
    },
  });

  async function save() {
    setSaving(true);
    try {
      await updateScript(scriptId, { source: code });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <Suspense fallback={<div className="text-muted-foreground">Loading editor…</div>}>
        <MonacoEditor
          height="60vh"
          language={language === "python" ? "python" : "javascript"}
          value={code}
          onChange={(v) => setCode(v ?? "")}
        />
      </Suspense>
      <button
        onClick={save}
        disabled={saving}
        className="mt-3 rounded bg-primary px-4 py-2 text-primary-foreground"
      >
        {saving ? "Saving…" : "Save"}
      </button>
    </div>
  );
}

function DepsTab({ scriptId }: { scriptId: number }) {
  const qc = useQueryClient();
  const { data: deps } = useQuery({ queryKey: ["deps", scriptId], queryFn: () => getDeps(scriptId) });
  const [list, setList] = useState<string[]>(() => deps?.deps ?? []);
  const [draft, setDraft] = useState("");

  const detect = useMutation({
    mutationFn: () => detectDeps(scriptId),
    onSuccess: (d) => setList(d.deps),
  });
  const save = useMutation({
    mutationFn: () => setDeps(scriptId, { deps: list, source: "manual" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["deps", scriptId] }),
  });

  return (
    <div>
      <div className="mb-3 flex gap-2">
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          className="rounded border px-3 py-1 text-sm"
        >
          {detect.isPending ? "Detecting…" : "Detect from source"}
        </button>
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
        >
          {save.isPending ? "Saving…" : "Save deps"}
        </button>
      </div>
      <div className="mb-3 flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="package name"
          className="flex-1 rounded border px-3 py-1 text-sm"
        />
        <button
          onClick={() => {
            if (draft && !list.includes(draft)) {
              setList([...list, draft]);
              setDraft("");
            }
          }}
          className="rounded border px-3 py-1 text-sm"
        >
          Add
        </button>
      </div>
      <ul className="space-y-1">
        {list.map((d) => (
          <li key={d} className="flex items-center justify-between rounded border px-3 py-1 text-sm">
            <span className="font-mono">{d}</span>
            <button onClick={() => setList(list.filter((x) => x !== d))} className="text-destructive">
              remove
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EnvTab({ scriptId }: { scriptId: number }) {
  const { data: info } = useQuery({ queryKey: ["env", scriptId], queryFn: () => getEnv(scriptId) });
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () => setEnv(scriptId, content),
    onSuccess: () => setSaved(true),
  });
  const clear = useMutation({
    mutationFn: () => deleteEnv(scriptId),
    onSuccess: () => setContent(""),
  });

  return (
    <div>
      <p className="mb-2 text-sm text-muted-foreground">
        {info?.has_env ? `Stored (${info.line_count} lines). Encrypted at rest.` : "No env stored."}
      </p>
      <textarea
        value={content}
        onChange={(e) => { setContent(e.target.value); setSaved(false); }}
        rows={12}
        placeholder={"KEY=value\nANOTHER=thing"}
        className="w-full rounded border px-3 py-2 font-mono text-sm"
      />
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
        >
          {save.isPending ? "Saving…" : "Save env"}
        </button>
        <button
          onClick={() => clear.mutate()}
          disabled={clear.isPending}
          className="rounded border px-3 py-1 text-sm text-destructive"
        >
          Delete env
        </button>
        {saved && <span className="text-sm text-emerald-700">Saved.</span>}
      </div>
    </div>
  );
}
