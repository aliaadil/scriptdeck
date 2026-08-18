import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { QuickStartCards } from "@/components/editor/QuickStartCards";
import { createScript } from "@/api/scripts";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { toast } from "@/components/ui/sonner";

export function ScriptNew() {
  const nav = useNavigate();
  const [name, setName] = useState("Untitled script");
  const create = useMutation({
    mutationFn: (language: "python" | "node" | "bash") =>
      createScript({ name, language, template: language }),
    onSuccess: (s) => {
      toast.success("Script created");
      nav(`/scripts/${s.id}`);
    },
    onError: (e: Error) => toast.error(e.message ?? "Failed to create script"),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-6 p-6">
        <h1 className="text-2xl font-semibold">New script</h1>
        <p className="text-sm text-muted-foreground">Pick a language to get started.</p>
        <div className="space-y-2">
          <Label htmlFor="new-name">Name</Label>
          <Input id="new-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <QuickStartCards onPick={(l) => create.mutate(l)} />
        <Card className="border-dashed">
          <CardContent className="flex items-center justify-between p-4 text-sm">
            <span className="text-muted-foreground">Prefer to start blank?</span>
            <Button variant="outline" onClick={() => create.mutate("python")}>
              Blank editor
            </Button>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}