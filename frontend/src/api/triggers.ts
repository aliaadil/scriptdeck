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
  // Stored as either a JSON object (legacy env-var path) or a JSON array
  // (argv path, same on-wire shape as Manual Run's params_argv). The
  // frontend always writes argv now and renders both shapes for read.
  params_json?: Record<string, unknown> | unknown[] | null;
  run_count: number;
};

/** Body for create / update. Exactly one of params_json / params_argv. */
export type TriggerBody = {
  kind: TriggerKind;
  expression?: string | null;
  enabled?: boolean;
  timezone?: string | null;
  overlap_policy?: "skip" | "queue" | "parallel";
  retry_max?: number;
  retry_backoff?: number;
  queue_max?: number;
  params_json?: Record<string, unknown>;
  params_argv?: string[];
  rotate_token?: boolean;
};

export type CreateTriggerResponse = Trigger & { token?: string };

export const listTriggers = (scriptId: number) =>
  api<Trigger[]>(`/scripts/${scriptId}/triggers`);

export const createTrigger = (scriptId: number, body: TriggerBody) =>
  api<CreateTriggerResponse>(`/scripts/${scriptId}/triggers`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateTrigger = (
  scriptId: number,
  triggerId: number,
  body: TriggerBody,
) =>
  api<CreateTriggerResponse>(`/scripts/${scriptId}/triggers/${triggerId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteTrigger = (scriptId: number, triggerId: number) =>
  api<void>(`/scripts/${scriptId}/triggers/${triggerId}`, { method: "DELETE" });