import { useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import { putScriptFile } from "@/api/scripts";

type Props = {
  scriptId: number;
  path: string;
  initialContent: string;
  language: "python" | "node" | "bash";
  onSaved: () => void;
  onError: (msg: string) => void;
};

const DEBOUNCE_MS = 1500;

export function EditorPanel({ scriptId, path, initialContent, language, onSaved, onError }: Props) {
  const [content, setContent] = useState(initialContent);
  const [dirty, setDirty] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSaved = useRef(initialContent);

  // Keep the latest callbacks in refs so that a parent re-render passing new
  // inline arrow functions does not re-run the debounce effect and restart the
  // timer (which would postpone the save indefinitely while typing).
  const onSavedRef = useRef(onSaved);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onSavedRef.current = onSaved;
    onErrorRef.current = onError;
  });

  // Reset on path change
  useEffect(() => {
    setContent(initialContent);
    setDirty(false);
    lastSaved.current = initialContent;
  }, [path, initialContent]);

  useEffect(() => {
    if (content === lastSaved.current) {
      setDirty(false);
      return;
    }
    setDirty(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        await putScriptFile(scriptId, path, content);
        lastSaved.current = content;
        setDirty(false);
        onSavedRef.current();
      } catch (e) {
        onErrorRef.current((e as Error).message ?? "Save failed");
      }
    }, DEBOUNCE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [content, scriptId, path]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-8 items-center justify-between border-b bg-muted/30 px-3 text-xs">
        <span className="font-mono">{path}</span>
        <span className={dirty ? "text-amber-600" : "text-muted-foreground"}>
          {dirty ? "Unsaved" : "Saved"}
        </span>
      </div>
      <div className="flex-1 overflow-hidden bg-[#1e1e1e]">
        <Editor
          height="100%"
          language={language}
          value={content}
          theme="vs-dark"
          onChange={(v) => setContent(v ?? "")}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            scrollBeyondLastLine: false,
            automaticLayout: true,
          }}
        />
      </div>
    </div>
  );
}
