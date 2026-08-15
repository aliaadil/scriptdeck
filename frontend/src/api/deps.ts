import { api } from "./client";

export type Deps = { deps: string[]; source: "auto" | "manual" };

export const getDeps = (scriptId: number) => api<Deps>(`/api/scripts/${scriptId}/deps`);
export const detectDeps = (scriptId: number) =>
  api<Deps>(`/api/scripts/${scriptId}/deps/detect`, { method: "POST" });
export const setDeps = (scriptId: number, body: Deps) =>
  api<Deps>(`/api/scripts/${scriptId}/deps`, { method: "PUT", body: JSON.stringify(body) });
