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

export function ScriptEdit() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const isNew = id === "new";
  const { data: script } = useQuery({
    queryKey: ["script", id],
    queryFn: () => api<Script>(`/api/scripts/${id}`),
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
  const run = useMutation({
    mutationFn: () => api(`/api/scripts/${id}/run`, { method: "POST", body: "{}" }),
    onSuccess: () => toast.success("Run started"),
    onError: (e: Error) => toast.error(e.message),
  });
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
        <div className="flex items-center justify-between gap-4">
          <h1 className="truncate text-2xl font-semibold">
            {isNew ? "New script" : script?.name ?? "Loading…"}
          </h1>
          <div className="flex shrink-0 gap-2">
            <Button
              variant="outline"
              onClick={() => run.mutate()}
              disabled={isNew || !script}
              title={isNew ? "Save the script first to enable Run" : undefined}
            >
              <Play className="mr-2 h-4 w-4" /> Run
            </Button>
            <Button onClick={handleSave} disabled={!canSave || save.isPending}>
              <Save className="mr-2 h-4 w-4" /> {save.isPending ? "Saving…" : "Save"}
            </Button>
            {!isNew && (
              <Button variant="destructive" onClick={() => del.mutate()}>
                <Trash2 className="mr-2 h-4 w-4" /> Delete
              </Button>
            )}
          </div>
        </div>

        <Tabs defaultValue="editor">
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
              <CardContent className="font-mono text-xs">
                <pre>Run the script to see logs.</pre>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}
