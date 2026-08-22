import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Play, Trash2, X } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { API_BASE, getToken } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/sonner";
import { FileTree } from "@/components/editor/FileTree";
import { EditorPanel } from "@/components/editor/EditorPanel";
import { FileDialog } from "@/components/editor/FileDialog";
import { useAuth } from "@/auth/AuthProvider";
import { TriggersTab } from "@/components/schedules/TriggersTab";
import { LogViewer } from "@/components/runs/LogViewer";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  listScriptsFiles,
  getScriptFile,
  deleteScriptFile,
  createScriptFile,
  updateScriptEntrypoint,
  updateScript,
  type FileEntry,
  type ScriptOut,
} from "@/api/scripts";
import { listRuns, cancelRun } from "@/api/runs";
import { ApiError } from "@/api/client";

type RunInfo = {
  id: number;
  script_id: number;
  status: "running" | "success" | "failure" | "error" | "cancelled";
  exit_code: number | null;
  started_at: string;
  ended_at: string | null;
  trigger_kind?: string | null;
};

type EditorLanguage = "python" | "node" | "bash";

/** Extensions that can serve as a script entrypoint. */
const ENTRYPOINT_EXTENSIONS = [".py", ".js", ".ts", ".mjs", ".cjs", ".sh"];

function isEntrypointCandidate(path: string): boolean {
  return ENTRYPOINT_EXTENSIONS.some((ext) => path.endsWith(ext));
}

function languageForPath(path: string | null): EditorLanguage {
  if (!path) return "python";
  if (path.endsWith(".py")) return "python";
  if (path.endsWith(".sh")) return "bash";
  if (
    path.endsWith(".js") ||
    path.endsWith(".ts") ||
    path.endsWith(".mjs") ||
    path.endsWith(".cjs")
  ) {
    return "node";
  }
  return "python";
}

function RunTriggerBadge({ kind }: { kind: string | null }) {
  if (!kind) return null;
  const label =
    kind === "cron"
      ? "via cron"
      : kind === "interval"
      ? "via interval"
      : kind === "webhook"
      ? "via webhook"
      : kind === "manual"
      ? "manual"
      : `via ${kind}`;
  return (
    <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px]" data-testid="run-trigger-badge">
      {label}
    </span>
  );
}

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
  const { user } = useAuth();

  // Creating a script now lives on its own page; bounce any stale /scripts/new
  // links that still resolve to this route.
  const isNew = id === "new";
  useEffect(() => {
    if (isNew) nav("/kindling/scripts/new", { replace: true });
  }, [isNew, nav]);

  const scriptId = Number(id);
  const scriptIdValid = !isNew && Number.isFinite(scriptId);

  const { data: script } = useQuery<ScriptOut>({
    queryKey: ["script", scriptId],
    queryFn: () => api<ScriptOut>(`/scripts/${scriptId}`),
    enabled: scriptIdValid,
  });

  const { data: files = [], refetch: refetchFiles } = useQuery<FileEntry[]>({
    queryKey: ["script-files", scriptId],
    queryFn: () => listScriptsFiles(scriptId),
    enabled: scriptIdValid,
  });

  const [activePath, setActivePath] = useState<string | null>(null);
  const [activeContent, setActiveContent] = useState("");
  const [dialog, setDialog] = useState<null | "add">(null);
  const activeLang = useMemo(() => languageForPath(activePath), [activePath]);

  // Config tab form state, seeded from the loaded script.
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  useEffect(() => {
    if (!script) return;
    setName(script.name ?? "");
    setDescription(script.description ?? "");
  }, [script]);

  // Pick a sensible default file once the tree loads (or after the active file
  // is deleted): the entrypoint if it still exists, else the first file.
  useEffect(() => {
    if (activePath || files.length === 0) return;
    const entrypoint = script?.entrypoint;
    setActivePath(files.find((f) => f.path === entrypoint)?.path ?? files[0].path);
  }, [files, activePath, script]);

  // Load the active file's content. The `cancelled` guard keeps a slow response
  // for a previously-selected file from overwriting the current one.
  useEffect(() => {
    if (!activePath || !scriptIdValid) return;
    let cancelled = false;
    setActiveContent("");
    getScriptFile(scriptId, activePath)
      .then((content) => {
        if (!cancelled) setActiveContent(content);
      })
      .catch((e: Error) => {
        if (!cancelled) toast.error(e.message ?? "Failed to load file");
      });
    return () => {
      cancelled = true;
    };
  }, [activePath, scriptId, scriptIdValid]);

  const del = useMutation({
    mutationFn: (path: string) => deleteScriptFile(scriptId, path),
    onSuccess: (_data, path) => {
      toast.success("File deleted");
      refetchFiles();
      // Clearing the selection lets the default-file effect re-select.
      if (activePath === path) setActivePath(null);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const add = useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      createScriptFile(scriptId, path, content),
    onSuccess: (_data, { path }) => {
      toast.success("File added");
      refetchFiles();
      setDialog(null);
      setActivePath(path);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const updateEntrypoint = useMutation({
    mutationFn: (entrypoint: string) => updateScriptEntrypoint(scriptId, entrypoint),
    onSuccess: () => {
      toast.success("Entrypoint updated");
      qc.invalidateQueries({ queryKey: ["script", scriptId] });
      qc.invalidateQueries({ queryKey: ["scripts"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const saveMeta = useMutation({
    mutationFn: () =>
      updateScript(scriptId, {
        name: name.trim(),
        description: description.trim() || null,
      }),
    onSuccess: () => {
      toast.success("Saved");
      qc.invalidateQueries({ queryKey: ["script", scriptId] });
      qc.invalidateQueries({ queryKey: ["scripts"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const run = useMutation<RunInfo, Error, void>({
    mutationFn: () => api<RunInfo>(`/scripts/${scriptId}/run`, { method: "POST" }),
    onError: (e: Error) => toast.error(e.message ?? "Run failed to start"),
  });

  const recentRuns = useQuery({
    queryKey: ["runs", "by-script", scriptId],
    queryFn: () => listRuns({ script_id: scriptId, limit: 20 }),
    enabled: scriptIdValid,
    refetchInterval: 5000,
  });

  // Force-stop a stuck running row. The backend kills the live subprocess
  // (if any) and marks status='cancelled' even when the runner died without
  // finalizing, so the user never has to edit the DB by hand.
  const cancelRecent = useMutation({
    mutationFn: (id: number) => cancelRun(id),
    onSuccess: () => {
      toast.success("Run cancelled");
      qc.invalidateQueries({ queryKey: ["runs", "by-script", scriptId] });
      qc.invalidateQueries({ queryKey: ["run", currentRunId] });
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.status === 404) toast.error("Already finished");
      else toast.error(e.message);
      qc.invalidateQueries({ queryKey: ["runs", "by-script", scriptId] });
    },
  });

  const delScript = useMutation({
    mutationFn: () => api<void>(`/scripts/${scriptId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Deleted");
      nav("/kindling/scripts");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // --- Run + log viewer (Logs tab) ---
  const [activeTab, setActiveTab] = useState("editor");
  const [currentRunId, setCurrentRunId] = useState<number | null>(null);
  const [runLog, setRunLog] = useState("");

  useEffect(() => {
    if (!run.data) return;
    setCurrentRunId(run.data.id);
    setActiveTab("logs");
    setRunLog("");
    toast.info(`Run #${run.data.id} started`);
  }, [run.data]);

  const runStatus = useQuery<RunInfo>({
    queryKey: ["run", currentRunId],
    queryFn: () => api<RunInfo>(`/runs/${currentRunId}`),
    enabled: currentRunId != null,
    refetchInterval: (q) => {
      const s = q.state.data;
      return s && s.status !== "running" ? false : 1000;
    },
  });

  useEffect(() => {
    if (!runStatus.data) return;
    if (runStatus.data.status === "running") return;
    const { id: runId, status, exit_code: exit } = runStatus.data;
    if (status === "success") toast.success(`Run #${runId} finished (exit 0)`);
    else if (status === "failure") toast.error(`Run #${runId} failed (exit ${exit})`);
    else if (status === "error") toast.error(`Run #${runId} crashed`);
    else if (status === "cancelled") toast.warning(`Run #${runId} cancelled`);
  }, [runStatus.data]);

  // Refresh log content whenever the polled run finishes.
  useEffect(() => {
    if (!currentRunId) return;
    if (runStatus.data?.status === "running") return;
    let cancelled = false;
    (async () => {
      try {
        const token = getToken();
        const res = await fetch(`${API_BASE}/runs/${currentRunId}/log`, {
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

  if (isNew) return null;
  if (!script) {
    return (
      <AppShell>
        <div className="p-6 text-sm text-muted-foreground">Loading…</div>
      </AppShell>
    );
  }

  // Always offer the current entrypoint, even if it has an unusual extension.
  const entrypointOptions = files
    .map((f) => f.path)
    .filter((p) => isEntrypointCandidate(p) || p === script.entrypoint);

  // Dirty state for the header Save button: name or description differs
  // from what the server last returned.
  const trimmedName = name.trim();
  const metaDirty =
    trimmedName !== (script.name ?? "").trim() ||
    description !== (script.description ?? "");
  const canSaveMeta = metaDirty && trimmedName.length > 0 && !saveMeta.isPending;

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-4rem)] flex-col">
        <header className="flex shrink-0 flex-col gap-1 border-b px-4 py-1.5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <Input
                aria-label="Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Script name"
                className="h-8 max-w-md font-semibold"
                data-testid="name-input"
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => saveMeta.mutate()}
                disabled={!canSaveMeta}
                title={
                  !trimmedName
                    ? "Name cannot be empty"
                    : !metaDirty
                    ? "No changes to save"
                    : undefined
                }
                data-testid="save-meta"
              >
                <Save className="mr-2 h-4 w-4" /> {saveMeta.isPending ? "Saving…" : "Save"}
              </Button>
              <span className="truncate text-xs text-muted-foreground">{script.language}</span>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button
                variant="outline"
                onClick={() => run.mutate()}
                disabled={!script || run.isPending}
                className="min-h-10"
              >
                <Play className="mr-2 h-4 w-4" /> {run.isPending ? "Starting…" : "Run"}
              </Button>
              <Button
                variant="destructive"
                onClick={() => {
                  if (window.confirm(`Delete script "${script.name}"?`)) delScript.mutate();
                }}
                disabled={delScript.isPending}
                title="Delete script"
                className="min-h-10"
              >
                <Trash2 className="mr-2 h-4 w-4" /> Delete
              </Button>
            </div>
          </div>
          <Textarea
            aria-label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            rows={1}
            className="min-h-0 resize-none text-xs leading-tight"
            data-testid="description-input"
          />
        </header>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="mx-4 self-start">
            <TabsTrigger value="editor">Editor</TabsTrigger>
            <TabsTrigger value="triggers">Triggers</TabsTrigger>
            <TabsTrigger value="logs">Logs</TabsTrigger>
          </TabsList>

          {/* Absolute-position the active panel so all tabs render from the
              top of the available area. Without this, the Editor tabpanel's
              `flex-1` soaks the leftover flex space even when inactive
              (Radix keeps the wrapper mounted), pushing the active form
              panel below the fold. */}
          <div className="relative min-h-0 flex-1">
            <TabsContent value="editor" className="absolute inset-0 mt-2 flex overflow-hidden data-[state=inactive]:hidden">
            <div className="md:hidden px-4 pb-2">
              {activePath !== null && (
                <Select
                  value={activePath}
                  onValueChange={setActivePath}
                  disabled={files.length === 0}
                >
                  <SelectTrigger aria-label="Select file" className="w-full min-h-10">
                    <SelectValue placeholder="Select file" />
                  </SelectTrigger>
                  <SelectContent>
                    {files.map((f) => (
                      <SelectItem key={f.path} value={f.path}>
                        {f.path}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <FileTree
              files={files}
              active={activePath}
              onSelect={setActivePath}
              onAdd={() => setDialog("add")}
              onUpload={() => toast.info("File upload is coming in a later release.")}
              onDelete={(p) => {
                if (window.confirm(`Delete ${p}?`)) del.mutate(p);
              }}
              language={script.language}
              entrypoint={script.entrypoint}
              entrypointOptions={entrypointOptions}
              onEntrypointChange={(p) => updateEntrypoint.mutate(p)}
            />
            <div className="min-w-0 flex-1">
              {activePath ? (
                <EditorPanel
                  scriptId={scriptId}
                  path={activePath}
                  initialContent={activeContent}
                  language={activeLang}
                  onSaved={() => refetchFiles()}
                  onError={(m) => toast.error(m)}
                />
              ) : (
                <div className="p-6 text-sm text-muted-foreground">
                  No file selected. Add a file to get started.
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="triggers" className="absolute inset-0 overflow-auto data-[state=inactive]:hidden">
            {scriptIdValid ? <TriggersTab scriptId={scriptId} /> : null}
          </TabsContent>

          <TabsContent value="logs" className="absolute inset-0 overflow-auto p-4 data-[state=inactive]:hidden">
            <div className="space-y-4">
              <Card>
                <CardContent className="space-y-2 p-4">
                  <h3 className="text-sm font-medium">Recent runs</h3>
                  {recentRuns.data && recentRuns.data.length > 0 ? (
                    <div className="divide-y">
                      {recentRuns.data.map((r) => (
                        <div
                          key={r.id}
                          data-testid={`recent-run-${r.id}`}
                          onClick={() => {
                            setCurrentRunId(r.id);
                            setRunLog("");
                          }}
                          className={`flex w-full cursor-pointer items-center justify-between gap-2 py-1 hover:bg-muted/50 ${
                            currentRunId === r.id ? "bg-muted/40" : ""
                          }`}
                        >
                          <span className="flex items-center gap-2">
                            <span className="font-mono text-xs">#{r.id}</span>
                            <RunStatusBadge status={r.status} exitCode={r.exit_code} />
                            <span className="text-xs text-muted-foreground">
                              {new Date(r.started_at).toLocaleString()}
                            </span>
                            {r.trigger_kind ? <RunTriggerBadge kind={r.trigger_kind} /> : null}
                          </span>
                          <span className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground">
                              exit {r.exit_code ?? "—"}
                            </span>
                            {r.status === "running" && user?.role !== "viewer" && (
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Cancel run ${r.id}`}
                                data-testid={`cancel-run-${r.id}`}
                                disabled={cancelRecent.isPending}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  cancelRecent.mutate(r.id);
                                }}
                              >
                                <X className="h-4 w-4" />
                              </Button>
                            )}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">No runs yet.</p>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardContent className="space-y-3 p-4">
                  {currentRunId == null ? (
                    <p className="text-sm text-muted-foreground">
                      Pick a run above, or hit Run in the header.
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
                      <LogViewer
                        className="max-h-[60vh] overflow-auto rounded-md border bg-[#1e1e1e] p-3 font-mono text-[13px] leading-relaxed text-zinc-100"
                        text={
                          runStatus.data?.status === "running" && !runLog
                            ? "Waiting for output…"
                            : runLog || "(no output)"
                        }
                      />
                    </>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
          </div>
        </Tabs>

        {dialog === "add" && (
          <FileDialog
            mode="add"
            onSubmit={(path) => add.mutate({ path, content: "" })}
            onCancel={() => setDialog(null)}
          />
        )}
      </div>
    </AppShell>
  );
}
