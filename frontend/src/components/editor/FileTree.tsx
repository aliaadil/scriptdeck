import { FilePlus2, Upload, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { FileEntry } from "@/api/scripts";

type Props = {
  files: FileEntry[];
  active: string | null;
  onSelect: (path: string) => void;
  onAdd: () => void;
  onUpload: () => void;
  onDelete: (path: string) => void;
};

function buildTree(files: FileEntry[]): Map<string, FileEntry[]> {
  const groups = new Map<string, FileEntry[]>();
  for (const f of files) {
    const dir = f.path.includes("/") ? f.path.split("/").slice(0, -1).join("/") : "";
    if (!groups.has(dir)) groups.set(dir, []);
    groups.get(dir)!.push(f);
  }
  return groups;
}

export function FileTree({ files, active, onSelect, onAdd, onUpload, onDelete }: Props) {
  const groups = buildTree(files);
  return (
    <aside
      className="hidden md:flex h-full w-56 flex-col gap-2 border-r bg-muted/30 p-2"
      data-testid="file-tree"
    >
      <div className="flex gap-1">
        <Button size="sm" variant="outline" onClick={onAdd} title="Add file">
          <FilePlus2 className="h-3 w-3" />
        </Button>
        <Button size="sm" variant="outline" onClick={onUpload} title="Upload file">
          <Upload className="h-3 w-3" />
        </Button>
      </div>
      <ul className="flex-1 overflow-auto text-sm">
        {[...groups.entries()].map(([dir, items]) => (
          <li key={dir || "/"}>
            {dir && <div className="px-1 py-0.5 text-xs text-muted-foreground">{dir}/</div>}
            <ul>
              {items.map((f) => {
                const name = f.path.split("/").pop()!;
                const isActive = f.path === active;
                return (
                  <li
                    key={f.path}
                    data-active={isActive ? "true" : undefined}
                    className="group flex items-center"
                  >
                    <button
                      onClick={() => onSelect(f.path)}
                      className={[
                        "flex-1 truncate rounded px-2 py-1 text-left",
                        isActive ? "bg-primary/10 text-primary" : "hover:bg-muted",
                      ].join(" ")}
                    >
                      {name}
                    </button>
                    <button
                      onClick={() => onDelete(f.path)}
                      className="invisible px-1 text-muted-foreground hover:text-destructive group-hover:visible"
                      title="Delete file"
                      aria-label={`Delete ${name}`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ul>
    </aside>
  );
}