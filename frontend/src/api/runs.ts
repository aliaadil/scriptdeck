import { api } from "./client";

export type Run = {
  id: number; script_id: number; schedule_id: number | null;
  started_at: string; ended_at: string | null; exit_code: number | null; status: string;
  attempt: number; retry_group: string | null;
};

export const listRunGroup = (group: string) =>
  api<Run[]>(`/runs?group=${encodeURIComponent(group)}`);

export const listRuns = (params?: { script_id?: number; status?: string }) => {
  const q = new URLSearchParams();
  if (params?.script_id) q.set("script_id", String(params.script_id));
  if (params?.status) q.set("status_filter", params.status);
  const qs = q.toString();
  return api<Run[]>(`/runs${qs ? `?${qs}` : ""}`);
};
export const getRun = (id: number) => api<Run>(`/runs/${id}`);
export const triggerRun = (script_id: number) =>
  api<Run>("/runs", { method: "POST", body: JSON.stringify({ script_id }) });
export const cancelRun = (id: number) =>
  api(`/runs/${id}/cancel`, { method: "POST" });
