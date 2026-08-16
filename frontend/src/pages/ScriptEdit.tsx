import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
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

export function ScriptEdit() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const isNew = id === "new";
  const { data: script } = useQuery({
    queryKey: ["script", id],
    queryFn: () => api<{ id: string; name: string; language: string; source: string; description?: string }>(`/api/scripts/${id}`),
    enabled: !isNew,
  });
  const save = useMutation({
    mutationFn: (body: unknown) =>
      isNew
        ? api("/api/scripts", { method: "POST", body: JSON.stringify(body) })
        : api(`/api/scripts/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Saved");
    },
    onError: (e: Error) => toast.error(e.message),
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

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">{isNew ? "New script" : script?.name ?? "Loading…"}</h1>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => run.mutate()} disabled={isNew}>
              <Play className="mr-2 h-4 w-4" /> Run
            </Button>
            <Button onClick={() => save.mutate(script)} disabled={!script}>
              <Save className="mr-2 h-4 w-4" /> Save
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
              <CardContent className="p-0">
                <Editor
                  height="60vh"
                  defaultLanguage={script?.language ?? "python"}
                  value={script?.source ?? ""}
                  theme="vs-dark"
                  options={{ minimap: { enabled: false } }}
                />
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="config">
            <Card>
              <CardContent className="space-y-4 pt-6">
                <div className="space-y-2">
                  <Label htmlFor="name">Name</Label>
                  <Input id="name" defaultValue={script?.name} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="desc">Description</Label>
                  <Textarea id="desc" defaultValue={script?.description} />
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