import { api } from "./client";

export type AuditEntry = {
  id: number; user_id: number | null; action: string;
  resource_type: string; resource_id: number | null; at: string; meta_json: string;
};

export const listUsers = () => api<Array<{ id: number; email: string; role: string }>>("/api/users/");
export const createInvite = (email: string, role: "admin" | "editor" | "viewer") =>
  api<{ token: string; expires_at: string }>("/api/users/invites", {
    method: "POST", body: JSON.stringify({ email, role }),
  });
export const changeRole = (userId: number, role: "admin" | "editor" | "viewer") =>
  api(`/api/users/${userId}/role`, { method: "PUT", body: JSON.stringify({ role }) });
export const deleteUser = (userId: number) =>
  api(`/api/users/${userId}`, { method: "DELETE" });
export const listAudit = (params?: { user_id?: number; resource?: string }) => {
  const q = new URLSearchParams();
  if (params?.user_id) q.set("user_id", String(params.user_id));
  if (params?.resource) q.set("resource", params.resource);
  return api<AuditEntry[]>(`/api/admin/audit${q.toString() ? `?${q}` : ""}`);
};
