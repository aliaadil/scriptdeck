import { api } from "./client";
import type { Run } from "./runs";

export type FileEntry = {
  path: string;
  size: number;
  updated_at: string;
};

export type ScriptOut = {
  id: number;
  name: string;
  language: "python" | "node" | "bash";
  source_path: string;
  entrypoint: string;
  description: string | null;
};

// Backwards-compatible alias used by existing call sites (e.g. ScheduleForm).
export type Script = {
  id: number;
  name: string;
  language: "python" | "node" | "bash";
  source_path: string;
  description: string | null;
};

export const listScripts = () => api<Script[]>("/scripts");
export const getScript = (id: number) => api<Script>(`/scripts/${id}`);
export const deleteScript = (id: number) =>
  api<void>(`/scripts/${id}`, { method: "DELETE" });

export const listScriptsFiles = (id: number) =>
  api<{ entries: FileEntry[] }>(`/scripts/${id}/files`).then((r) => r.entries);

export const getScriptFile = async (id: number, path: string): Promise<string> => {
  const r = await api<{ content: string }>(`/scripts/${id}/files/${encodeURI(path)}`);
  return r.content;
};

export const putScriptFile = (id: number, path: string, content: string) =>
  api<FileEntry>(`/scripts/${id}/files/${encodeURI(path)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });

export const deleteScriptFile = (id: number, path: string) =>
  api<void>(`/scripts/${id}/files/${encodeURI(path)}`, { method: "DELETE" });

export const createScriptFile = (id: number, path: string, content: string) =>
  api<FileEntry>(`/scripts/${id}/files`, {
    method: "POST",
    body: JSON.stringify({ path, content }),
  });

export const createScript = (body: {
  name: string;
  language: "python" | "node" | "bash";
  template?: "python" | "node" | "bash";
  description?: string | null;
}) => api<ScriptOut>("/scripts", { method: "POST", body: JSON.stringify(body) });

export const updateScript = (
  id: number,
  body: {
    name?: string;
    description?: string | null;
    entrypoint?: string;
  },
) => api<ScriptOut>(`/scripts/${id}`, { method: "PUT", body: JSON.stringify(body) });

export const updateScriptEntrypoint = (id: number, entrypoint: string) =>
  updateScript(id, { entrypoint });

/**
 * POST /scripts/{id}/run. When ``params_json`` is provided, the backend
 * persists it on the run row, exports KINDLING_PARAM_<KEY>=<value> env vars
 * (same as schedule/webhook triggers), and appends language-appropriate argv
 * after the entrypoint.
 */
export const triggerRun = (
  script_id: number,
  params_json?: Record<string, string | number | boolean>,
): Promise<Run> =>
  api<Run>(`/scripts/${script_id}/run`, {
    method: "POST",
    body: params_json ? JSON.stringify({ params_json }) : undefined,
  });
