import { api } from "./client";

export type Run = {
  id: number; script_id: number; schedule_id: number | null;
  // 'manual' / 'cron' / 'interval' / 'webhook' / null (legacy rows).
  trigger_kind: string | null;
  started_at: string; ended_at: string | null; exit_code: number | null; status: string;
  attempt: number; retry_group: string | null;
  params_json: Record<string, unknown> | null;
};

export const listRunGroup = (group: string) =>
  api<Run[]>(`/runs?group=${encodeURIComponent(group)}`);

export const listRuns = (params?: {
  script_id?: number;
  status?: string;
  limit?: number;
}) => {
  const q = new URLSearchParams();
  if (params?.script_id) q.set("script_id", String(params.script_id));
  if (params?.status) q.set("status_filter", params.status);
  if (params?.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return api<Run[]>(`/runs${qs ? `?${qs}` : ""}`);
};
export const getRun = (id: number) => api<Run>(`/runs/${id}`);
export const cancelRun = (id: number) =>
  api(`/runs/${id}/cancel`, { method: "POST" });
