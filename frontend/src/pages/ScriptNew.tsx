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
import { isPlaceholderName } from "@/lib/placeholder";

type Language = "python" | "node" | "bash";

export function ScriptNew() {
  const nav = useNavigate();
  const [name, setName] = useState("Untitled script");
  const trimmedName = name.trim();
  // Both the frontend button and the backend reject the placeholder name
  // (mirrored via `isPlaceholderName` / `UNTITLED_PLACEHOLDER`). We block
  // here too so a placeholder never reaches the network — saving the user
  // a 422 roundtrip and an extra toast.
  const nameInvalid = trimmedName.length === 0 || isPlaceholderName(trimmedName);
  const create = useMutation({
    mutationFn: (language: Language) =>
      createScript({ name: trimmedName, language, template: language }),
    onSuccess: (s) => {
      toast.success("Script created");
      nav(`/kindling/scripts/${s.id}`);
    },
    onError: (e: Error) => toast.error(e.message ?? "Failed to create script"),
  });

  const tryCreate = (language: Language) => {
    if (nameInvalid) {
      toast.error("Pick a unique name before creating a script.");
      return;
    }
    create.mutate(language);
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-6 p-6">
        <h1 className="text-2xl font-semibold">New script</h1>
        <p className="text-sm text-muted-foreground">Pick a language to get started.</p>
        <div className="space-y-2">
          <Label htmlFor="new-name">Name</Label>
          <Input
            id="new-name"
            className="w-full"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={nameInvalid}
            data-testid="new-name-input"
          />
          {nameInvalid && (
            <p
              className="text-xs text-destructive"
              role="alert"
              data-testid="new-name-prompt"
            >
              Pick a unique name before continuing — &ldquo;Untitled script&rdquo; is
              just a placeholder.
            </p>
          )}
        </div>
        <div data-testid="language-pickers" aria-disabled={nameInvalid}>
          <QuickStartCards
            onPick={(l) => tryCreate(l)}
            disabled={nameInvalid}
          />
        </div>
        <Card className="border-dashed">
          <CardContent className="flex w-full flex-col-reverse gap-2 p-4 text-sm md:flex-row md:items-center md:justify-between">
            <span className="text-muted-foreground">Prefer to start blank?</span>
            <Button
              variant="outline"
              onClick={() => tryCreate("python")}
              disabled={nameInvalid}
              data-testid="blank-editor"
            >
              Blank editor
            </Button>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
