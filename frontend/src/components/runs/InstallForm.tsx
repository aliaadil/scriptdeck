import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/sonner";
import { installPackages } from "@/api/install";

type Props = {
  scriptId: number;
  output: string;
  // Optional callback to refresh run data after a successful install
  // (e.g. so a re-run from the UI sees the new package). The Config tab
  // wraps the parent <RunView>'s auto-refresh, so this is a no-op by
  // default.
  onInstalled?: () => void;
};

// Mirrors the regex on the backend so the chip extractor can run
// in-browser without a round trip. Keep in sync with
// kindling.services.install.detect_missing_modules.
const PY_RE = /ModuleNotFoundError:\s*No module named\s*'([^']+)'/g;
const NODE_RE = /Cannot find module '([^']+)'/g;

function extractSuggestions(output: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of output.matchAll(PY_RE)) {
    const name = m[1].split(".")[0];
    if (name && !seen.has(name)) {
      seen.add(name);
      out.push(name);
    }
  }
  for (const m of output.matchAll(NODE_RE)) {
    const raw = m[1];
    let name: string;
    if (raw.startsWith("@")) {
      const parts = raw.split("/");
      name = parts.length >= 2 ? parts.slice(0, 2).join("/") : parts[0];
    } else {
      name = raw.split("/")[0];
    }
    if (name && !seen.has(name)) {
      seen.add(name);
      out.push(name);
    }
  }
  return out;
}

export function InstallForm({ scriptId, output, onInstalled }: Props) {
  const [draft, setDraft] = useState("");
  const qc = useQueryClient();
  const suggestions = useMemo(() => extractSuggestions(output), [output]);

  const mutation = useMutation({
    mutationFn: (packages: string[]) => installPackages(scriptId, packages),
    onSuccess: (res) => {
      toast.success(`Installed ${res.installed.join(", ")}`);
      setDraft("");
      // Invalidate deps so the deps panel (if any) reflects the new list.
      qc.invalidateQueries({ queryKey: ["deps", scriptId] });
      onInstalled?.();
    },
    onError: (err) => {
      toast.error((err as Error).message);
    },
  });

  function parse(raw: string): string[] {
    return raw
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }

  function submit() {
    const packages = parse(draft);
    if (packages.length === 0) return;
    mutation.mutate(packages);
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="package name (e.g. boto3)"
          className="font-mono text-xs"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          data-testid="install-input"
        />
        <Button
          size="sm"
          onClick={submit}
          disabled={mutation.isPending || parse(draft).length === 0}
          data-testid="install-button"
        >
          {mutation.isPending ? "Installing…" : "Install"}
        </Button>
      </div>
      {suggestions.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Suggested
          </span>
          {suggestions.map((name) => (
            <Badge
              key={name}
              variant="secondary"
              role="button"
              className="cursor-pointer font-mono text-[10px]"
              onClick={() => mutation.mutate([name])}
              data-testid={`install-suggest-${name}`}
            >
              {name}
            </Badge>
          ))}
        </div>
      )}
      {mutation.data && (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[11px] text-muted-foreground">
          {mutation.data.output || "(no output)"}
        </pre>
      )}
    </div>
  );
}
