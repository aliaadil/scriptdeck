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
 * POST /scripts/{id}/run. Exactly one of ``params_json`` (object) or
 * ``params_argv`` (list of strings) may be provided:
 *   - params_json: backend exports KINDLING_PARAM_<KEY>=<value> env vars
 *     (same as schedule/webhook triggers) and appends language-appropriate
 *     argv via argv_for.
 *   - params_argv: backend appends the list verbatim after the entrypoint.
 *     No env-var export. Lets the manual runner type CLI args the way
 *     they'd pass them on a shell — what you type is what runs.
 */
export const triggerRun = (
  script_id: number,
  params_json?: Record<string, string | number | boolean>,
  params_argv?: string[],
): Promise<Run> => {
  const body: Record<string, unknown> = {};
  if (params_json !== undefined) body.params_json = params_json;
  if (params_argv !== undefined) body.params_argv = params_argv;
  return api<Run>(`/scripts/${script_id}/run`, {
    method: "POST",
    body: Object.keys(body).length > 0 ? JSON.stringify(body) : undefined,
  });
};
