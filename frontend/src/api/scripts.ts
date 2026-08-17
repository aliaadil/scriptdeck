import { api } from "./client";

export type Script = {
  id: number;
  name: string;
  language: "python" | "node";
  source_path: string;
  description: string | null;
};

export const listScripts = () => api<Script[]>("/scripts");
export const getScript = (id: number) => api<Script>(`/scripts/${id}`);
export const createScript = (body: {
  name: string; language: "python" | "node"; source: string; description?: string;
}) => api<Script>("/scripts", { method: "POST", body: JSON.stringify(body) });
export const updateScript = (id: number, body: Partial<Script> & { source?: string }) =>
  api<Script>(`/scripts/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteScript = (id: number) =>
  api<void>(`/scripts/${id}`, { method: "DELETE" });
