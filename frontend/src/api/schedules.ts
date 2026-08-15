import { api } from "./client";

export type Schedule = {
  id: number; script_id: number; kind: "cron" | "interval"; expression: string;
  enabled: boolean; next_run_at: string; retry_max: number; retry_backoff: number;
};

export const listSchedules = (scriptId?: number) =>
  api<Schedule[]>(`/api/schedules${scriptId ? `?script_id=${scriptId}` : ""}`);
export const createSchedule = (body: Omit<Schedule, "id" | "next_run_at">) =>
  api<Schedule>("/api/schedules", { method: "POST", body: JSON.stringify(body) });
export const updateSchedule = (id: number, body: Omit<Schedule, "id" | "next_run_at">) =>
  api<Schedule>(`/api/schedules/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteSchedule = (id: number) =>
  api<void>(`/api/schedules/${id}`, { method: "DELETE" });
export const enableSchedule = (id: number) =>
  api(`/api/schedules/${id}/enable`, { method: "POST" });
export const disableSchedule = (id: number) =>
  api(`/api/schedules/${id}/disable`, { method: "POST" });
