import { api } from "./client";

export type EnvInfo = { has_env: boolean; line_count: number; updated_at: string | null };

export const getEnv = (scriptId: number) => api<EnvInfo>(`/api/scripts/${scriptId}/env`);
export const setEnv = (scriptId: number, content: string) =>
  api<EnvInfo>(`/api/scripts/${scriptId}/env`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
export const deleteEnv = (scriptId: number) =>
  api<{ ok: true }>(`/api/scripts/${scriptId}/env`, { method: "DELETE" });
