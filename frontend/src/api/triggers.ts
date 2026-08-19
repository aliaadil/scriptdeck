import { api } from "./client";

export type TriggerKind = "cron" | "interval" | "webhook";

export type Trigger = {
  id: number;
  script_id: number;
  kind: TriggerKind;
  expression: string | null;
  enabled: boolean;
  next_run_at: string | null;
  retry_max: number;
  retry_backoff: number;
  timezone?: string | null;
  overlap_policy: "skip" | "queue" | "parallel";
  queue_max: number;
  params_json?: Record<string, unknown> | null;
  run_count: number;
};

export type CreateTriggerResponse = Trigger & { token?: string };

export const listTriggers = (scriptId: number) =>
  api<Trigger[]>(`/scripts/${scriptId}/triggers`);

export const createTrigger = (
  scriptId: number,
  body: Partial<Trigger> & { kind: TriggerKind; rotate_token?: boolean },
) =>
  api<CreateTriggerResponse>(`/scripts/${scriptId}/triggers`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateTrigger = (
  scriptId: number,
  triggerId: number,
  body: Partial<Trigger> & { kind: TriggerKind; rotate_token?: boolean },
) =>
  api<CreateTriggerResponse>(`/scripts/${scriptId}/triggers/${triggerId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteTrigger = (scriptId: number, triggerId: number) =>
  api<void>(`/scripts/${scriptId}/triggers/${triggerId}`, { method: "DELETE" });