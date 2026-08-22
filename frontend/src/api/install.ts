import { api } from "./client";

export type InstallResult = { output: string; installed: string[] };

export const installPackages = (scriptId: number, packages: string[]) =>
  api<InstallResult>(`/scripts/${scriptId}/install`, {
    method: "POST",
    body: JSON.stringify({ packages }),
  });
