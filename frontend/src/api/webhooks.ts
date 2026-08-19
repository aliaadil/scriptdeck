import { api } from "./client";

export type Webhook = {
  id: number;
  script_id: number;
  enabled: boolean;
  params: Record<string, string> | null;
  description: string | null;
  created_at: string;
  last_fired_at: string | null;
  fire_count: number;
};

/** Returned only on create / regenerate so the SPA can copy the URL once. */
export type WebhookCreated = Webhook & {
  secret_token: string;
  url?: string | null;
};

export type WebhookCreateBody = {
  script_id: number;
  description?: string | null;
  params?: Record<string, string> | null;
  enabled?: boolean;
};

export type WebhookPatchBody = {
  description?: string | null;
  enabled?: boolean;
  params?: Record<string, string> | null;
};

export const listWebhooks = (scriptId?: number) =>
  api<Webhook[]>(`/webhooks${scriptId !== undefined ? `?script_id=${scriptId}` : ""}`);
export const getWebhook = (id: number) => api<Webhook>(`/webhooks/${id}`);
export const createWebhook = (body: WebhookCreateBody) =>
  api<WebhookCreated>("/webhooks", { method: "POST", body: JSON.stringify(body) });
export const patchWebhook = (id: number, body: WebhookPatchBody) =>
  api<Webhook>(`/webhooks/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const regenerateWebhook = (id: number) =>
  api<WebhookCreated>(`/webhooks/${id}/regenerate`, { method: "POST" });
export const deleteWebhook = (id: number) =>
  api<void>(`/webhooks/${id}`, { method: "DELETE" });

// Per-script nested routes mirror the schedules pattern in Schedules.tsx.
export const listWebhooksForScript = (scriptId: number) =>
  api<Webhook[]>(`/scripts/${scriptId}/webhooks`);
export const createWebhookForScript = (scriptId: number, body: WebhookCreateBody) =>
  api<WebhookCreated>(`/scripts/${scriptId}/webhooks`, { method: "POST", body: JSON.stringify(body) });
