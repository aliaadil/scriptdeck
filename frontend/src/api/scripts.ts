import { api } from "./client";

export type Script = {
  id: number;
  name: string;
  language: "python" | "node";
  source_path: string;
  description: string | null;
};

export const listScripts = () => api<Script[]>("/api/scripts");
export const getScript = (id: number) => api<Script>(`/api/scripts/${id}`);
export const createScript = (body: {
  name: string; language: "python" | "node"; source: string; description?: string;
}) => api<Script>("/api/scripts", { method: "POST", body: JSON.stringify(body) });
export const updateScript = (id: number, body: Partial<Script> & { source?: string }) =>
  api<Script>(`/api/scripts/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteScript = (id: number) =>
  api<void>(`/api/scripts/${id}`, { method: "DELETE" });