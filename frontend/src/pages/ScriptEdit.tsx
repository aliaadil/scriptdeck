import { useEffect, useRef, useState, type DragEvent, type ChangeEvent } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
import { Upload, FileCode2 } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/sonner";
import { Save, Play, Trash2 } from "lucide-react";

type Script = { id: string; name: string; language: string; source: string; description?: string };

type RunInfo = {
  id: number;
  script_id: number;
  status: "running" | "success" | "failure" | "error" | "cancelled";
  exit_code: number | null;
  started_at: string;
  ended_at: string | null;
};

function RunStatusBadge({ status, exitCode }: { status: string; exitCode: number | null }) {
  const map: Record<string, string> = {
    success: "bg-success/15 text-success border-success/30",
    failure: "bg-destructive/15 text-destructive border-destructive/30",
    error: "bg-destructive/15 text-destructive border-destructive/30",
    running: "bg-secondary text-secondary-foreground border-transparent",
    cancelled: "bg-muted text-muted-foreground border-border",
  };
  const label =
    status === "running"
      ? "Running…"
      : status === "success"
      ? "Success"
      : status === "failure"
      ? `Failed (exit ${exitCode ?? "?"})`
      : status === "error"
      ? "Error"
      : "Cancelled";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${map[status] ?? "border-border text-foreground"}`}
    >
      {label}
    </span>
  );
}

export function ScriptEdit() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const isNew = id === "new";
  const { data: script } = useQuery({
    queryKey: ["script", id],
    queryFn: async () => {
      const meta = await api<Omit<Script, "source">>(`/api/scripts/${id}`);
      const token = localStorage.getItem("scriptdeck_token");
      const srcRes = await fetch(`/api/scripts/${id}/source`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      const source = srcRes.ok ? await srcRes.text() : "";
      return { ...meta, source } as Script;
    },
    enabled: !isNew,
  });

  // Source + language live in local state so the editor is editable for new scripts.
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState("");
  const [language, setLanguage] = useState<"python" | "node">("python");
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (script) {
      setName(script.name ?? "");
      setDescription(script.description ?? "");
      setSource(script.source ?? "");
      if (script.language === "python" || script.language === "node") {
        setLanguage(script.language);
      }
    }
  }, [script]);

  const save = useMutation<Script, Error, { name?: string; description?: string | null; source?: string; language?: "python" | "node" }>({
    mutationFn: (body) =>
      isNew
        ? api("/api/scripts", { method: "POST", body: JSON.stringify(body) })
        : api(`/api/scripts/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success(isNew ? "Script created" : "Saved");
      if (isNew && data?.id != null) nav(`/scripts/${data.id}`);
    },
    onError: (e) => toast.error(e.message),
  });
  const run = useMutation<RunInfo, Error, void>({
    mutationFn: () => api<RunInfo>(`/api/scripts/${id}/run`, { method: "POST" }),
    onSuccess: () => toast.success("Run started"),
    onError: (e: Error) => toast.error(e.message ?? "Run failed to start"),
  });

  const [activeTab, setActiveTab] = useState("editor");
  const [currentRunId, setCurrentRunId] = useState<number | null>(null);
  const [runLog, setRunLog] = useState<string>("");

  useEffect(() => {
    if (!run.data) return;
    setCurrentRunId(run.data.id);
    setActiveTab("logs");
    setRunLog("");
    toast.info(`Run #${run.data.id} started`);
  }, [run.data]);

  const runStatus = useQuery<RunInfo>({
    queryKey: ["run", currentRunId],
    queryFn: () => api<RunInfo>(`/api/runs/${currentRunId}`),
    enabled: currentRunId != null,
    refetchInterval: (q) => {
      const s = q.state.data;
      return s && s.status !== "running" ? false : 1000;
    },
  });

  useEffect(() => {
    if (!runStatus.data) return;
    if (runStatus.data.status === "running") return;
    const status = runStatus.data.status;
    const exit = runStatus.data.exit_code;
    if (status === "success") toast.success(`Run #${runStatus.data.id} finished (exit 0)`);
    else if (status === "failure") toast.error(`Run #${runStatus.data.id} failed (exit ${exit})`);
    else if (status === "error") toast.error(`Run #${runStatus.data.id} crashed`);
    else if (status === "cancelled") toast.warning(`Run #${runStatus.data.id} cancelled`);
  }, [runStatus.data]);

  // Refresh log content whenever the polled run finishes (and on tab open).
  useEffect(() => {
    if (!currentRunId) return;
    if (runStatus.data?.status === "running") return;
    let cancelled = false;
    (async () => {
      try {
        const token = localStorage.getItem("scriptdeck_token");
        const res = await fetch(`/api/runs/${currentRunId}/log`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!cancelled && res.ok) setRunLog(await res.text());
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentRunId, runStatus.data?.status]);
  const del = useMutation({
    mutationFn: () => api(`/api/scripts/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Deleted");
      nav("/scripts");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const canSave =
    isNew
      ? name.trim().length > 0 && source.trim().length > 0
      : Boolean(script);
  const handleSave = () => {
    if (isNew) {
      save.mutate({ name: name.trim(), description: description.trim() || null, source, language });
    } else {
      save.mutate({ name: name.trim() || undefined, description: description.trim() || null, source });
    }
  };

  const readFileText = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result ?? ""));
      reader.onerror = () => reject(reader.error ?? new Error("Failed to read file"));
      reader.readAsText(file);
    });

  const acceptFile = async (file: File) => {
    const lower = file.name.toLowerCase();
    if (lower.endsWith(".py")) setLanguage("python");
    else if (lower.endsWith(".js") || lower.endsWith(".ts") || lower.endsWith(".mjs") || lower.endsWith(".cjs"))
      setLanguage("node");
    else {
      toast.error("Unsupported file. Use .py, .js, .ts, .mjs, or .cjs");
      return;
    }
    try {
      const text = await readFileText(file);
      setSource(text);
    } catch (e) {
      toast.error((e as Error).message ?? "Failed to read file");
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) acceptFile(file);
  };
  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) acceptFile(file);
    e.target.value = "";
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1 space-y-2">
            <h1 className="truncate text-2xl font-semibold">
              {isNew ? "New script" : script?.name ?? "Loading…"}
            </h1>
            {isNew && (
              <div className="max-w-md space-y-1">
                <Label htmlFor="name-inline" className="sr-only">
                  Name
                </Label>
                <Input
                  id="name-inline"
                  placeholder="Script name (required to save)"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
            )}
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => run.mutate()}
                disabled={isNew || !script || run.isPending}
                title={isNew ? "Save the script first to enable Run" : undefined}
              >
                <Play className="mr-2 h-4 w-4" /> {run.isPending ? "Starting…" : "Run"}
              </Button>
              <Button
                onClick={handleSave}
                disabled={!canSave || save.isPending}
                title={
                  isNew && !canSave
                    ? name.trim().length === 0
                      ? "Enter a name to save"
                      : "Add some source code to save"
                    : undefined
                }
              >
                <Save className="mr-2 h-4 w-4" /> {save.isPending ? "Saving…" : "Save"}
              </Button>
              {!isNew && (
                <Button variant="destructive" onClick={() => del.mutate()}>
                  <Trash2 className="mr-2 h-4 w-4" /> Delete
                </Button>
              )}
            </div>
            {isNew && !canSave && (
              <p className="text-xs text-muted-foreground">
                {name.trim().length === 0
                  ? "Enter a name above to enable Save."
                  : "Add source code to enable Save."}
              </p>
            )}
          </div>
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="editor">Editor</TabsTrigger>
            <TabsTrigger value="config">Config</TabsTrigger>
            <TabsTrigger value="logs">Logs</TabsTrigger>
          </TabsList>

          <TabsContent value="editor">
            <Card>
              <CardContent className="space-y-3 p-4">
                <div
                  data-testid="script-dropzone"
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                  className={[
                    "flex items-center justify-between gap-3 rounded-md border border-dashed px-3 py-2 text-sm transition-colors",
                    dragOver
                      ? "border-primary bg-primary/5 text-foreground"
                      : "border-muted-foreground/25 text-muted-foreground",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-2">
                    <FileCode2 className="h-4 w-4" />
                    <span>
                      Drop a <code className="font-mono">.py</code> /{" "}
                      <code className="font-mono">.js</code> file or pick one to populate the editor.
                    </span>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Upload className="mr-2 h-4 w-4" /> Choose file
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".py,.js,.ts,.mjs,.cjs,text/*"
                    className="hidden"
                    onChange={onPick}
                  />
                </div>
                <div className="overflow-hidden rounded-md border bg-[#1e1e1e]">
                  <Editor
                    height="60vh"
                    language={language}
                    value={source}
                    theme="vs-dark"
                    onChange={(v) => setSource(v ?? "")}
                    options={{
                      minimap: { enabled: false },
                      fontSize: 13,
                      scrollBeyondLastLine: false,
                      automaticLayout: true,
                    }}
                  />
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="config">
            <Card>
              <CardContent className="space-y-4 pt-6">
                <div className="space-y-2">
                  <Label htmlFor="name">Name</Label>
                  <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="desc">Description</Label>
                  <Textarea
                    id="desc"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="logs">
            <Card>
              <CardContent className="space-y-3 p-4">
                {currentRunId == null ? (
                  <p className="text-sm text-muted-foreground">
                    Run the script to see logs.
                  </p>
                ) : (
                  <>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">Run #{currentRunId}</span>
                      <RunStatusBadge
                        status={runStatus.data?.status ?? "running"}
                        exitCode={runStatus.data?.exit_code ?? null}
                      />
                    </div>
                    <pre className="max-h-[60vh] overflow-auto rounded-md border bg-[#1e1e1e] p-3 font-mono text-[13px] leading-relaxed text-zinc-100">
                      {runStatus.data?.status === "running" && !runLog
                        ? "Waiting for output…"
                        : runLog || "(no output)"}
                    </pre>
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}
