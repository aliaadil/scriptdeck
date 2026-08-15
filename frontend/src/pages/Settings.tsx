import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import {
  changeRole, createInvite, deleteUser, listAudit, listUsers,
} from "@/api/admin";

export function Settings() {
  const qc = useQueryClient();
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const { data: audit } = useQuery({ queryKey: ["audit"], queryFn: () => listAudit() });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "editor" | "viewer">("viewer");
  const [inviteToken, setInviteToken] = useState<string | null>(null);

  const invite = useMutation({
    mutationFn: () => createInvite(email, role),
    onSuccess: (r) => setInviteToken(r.token),
  });
  const del = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
  const roleMut = useMutation({
    mutationFn: (args: { id: number; role: "admin" | "editor" | "viewer" }) =>
      changeRole(args.id, args.role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="mb-6 text-2xl font-semibold">Settings</h1>

        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold">Users</h2>
          <table className="w-full text-sm">
            <thead className="border-b text-left text-muted-foreground">
              <tr><th className="py-2">Email</th><th>Role</th><th></th></tr>
            </thead>
            <tbody>
              {users?.map((u) => (
                <tr key={u.id} className="border-b">
                  <td className="py-2">{u.email}</td>
                  <td>
                    <select
                      value={u.role}
                      onChange={(e) => roleMut.mutate({ id: u.id, role: e.target.value as "admin" | "editor" | "viewer" })}
                      className="rounded border px-2 py-1 text-sm"
                    >
                      <option value="admin">admin</option>
                      <option value="editor">editor</option>
                      <option value="viewer">viewer</option>
                    </select>
                  </td>
                  <td className="text-right">
                    <button onClick={() => del.mutate(u.id)} className="text-xs text-destructive">
                      delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <form
            onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}
            className="mt-4 flex gap-2"
          >
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="email"
              className="flex-1 rounded border px-3 py-1 text-sm"
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "editor" | "viewer")}
              className="rounded border px-2 py-1 text-sm"
            >
              <option value="viewer">viewer</option>
              <option value="editor">editor</option>
              <option value="admin">admin</option>
            </select>
            <button
              type="submit"
              disabled={invite.isPending}
              className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
            >
              Invite
            </button>
          </form>
          {inviteToken && (
            <div className="mt-2 rounded border bg-muted p-2 text-xs">
              Invite token (copy now, shown once): <code>{inviteToken}</code>
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">Audit log</h2>
          <table className="w-full text-sm">
            <thead className="border-b text-left text-muted-foreground">
              <tr><th className="py-2">At</th><th>User</th><th>Action</th><th>Resource</th></tr>
            </thead>
            <tbody>
              {audit?.map((a) => (
                <tr key={a.id} className="border-b">
                  <td className="py-2 font-mono text-xs">{a.at}</td>
                  <td>{a.user_id ?? "—"}</td>
                  <td>{a.action}</td>
                  <td>{a.resource_type}#{a.resource_id ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </AppShell>
  );
}
