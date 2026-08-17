import { api } from "./client";

export type SchedulePreset = { id: string; label: string; cron: string };

export const listPresets = () => api<SchedulePreset[]>("/schedule-presets");

export const fetchNextRuns = (scheduleId: number, limit = 5) =>
  api<string[]>(`/schedules/${scheduleId}/next-runs?limit=${limit}`);
