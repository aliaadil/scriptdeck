import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const PATH_RE = /^[a-zA-Z0-9._-]+(\/[a-zA-Z0-9._-]+)*$/;

type Props = {
  mode: "add" | "rename";
  initialPath?: string;
  onSubmit: (path: string) => void;
  onCancel: () => void;
};

export function FileDialog({ mode, initialPath = "", onSubmit, onCancel }: Props) {
  const [path, setPath] = useState(initialPath);
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    const trimmed = path.trim();
    if (!PATH_RE.test(trimmed)) {
      setError("Invalid path. Use letters, digits, dot, dash, underscore, slashes.");
      return;
    }
    if (trimmed.startsWith("/") || trimmed.includes("..")) {
      setError("Path cannot start with / or contain ..");
      return;
    }
    onSubmit(trimmed);
  };
  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === "add" ? "Add file" : "Rename file"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="file-path">Path</Label>
          <Input
            id="file-path"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="main.py or src/utils.py"
            autoFocus
            data-testid="file-path-input"
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button onClick={submit} data-testid="file-path-submit">{mode === "add" ? "Create" : "Rename"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
