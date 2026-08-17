import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/auth/AuthProvider";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "@/components/ui/sonner";
import { TimezoneSelect } from "@/components/users/TimezoneSelect";
import { api } from "@/api/client";
import {
  changeRole,
  createInvite,
  deleteUser,
  listAudit,
  listUsers,
} from "@/api/admin";

const ROLES = ["admin", "editor", "viewer"] as const;

export function Settings() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";

  const [instanceName, setInstanceName] = useState("Kindling");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "editor" | "viewer">("editor");
  const [lastInviteToken, setLastInviteToken] = useState<string | null>(null);
  // AuthProvider loads the user once and exposes no refetch, so hold the
  // timezone locally and treat the PATCH response as the source of truth.
  const [timezone, setTimezone] = useState(user?.timezone ?? "UTC");

  // `user` is null on first render while /auth/me is in flight; adopt the saved
  // timezone once it arrives so the select doesn't sit on a stale default.
  useEffect(() => {
    if (user?.timezone) setTimezone(user.timezone);
  }, [user?.timezone]);

  const timezoneMut = useMutation({
    mutationFn: (tz: string) =>
      api("/api/users/me", { method: "PATCH", body: JSON.stringify({ timezone: tz }) }),
    onSuccess: (_data, tz) => {
      setTimezone(tz);
      qc.invalidateQueries({ queryKey: ["auth-me"] });
      toast.success("Timezone updated");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: isAdmin,
  });
  const auditQuery = useQuery({
    queryKey: ["audit"],
    queryFn: () => listAudit(),
    enabled: isAdmin,
  });

  const createInviteMut = useMutation({
    mutationFn: () => createInvite(inviteEmail, inviteRole),
    onSuccess: (res) => {
      setLastInviteToken(res.token);
      setInviteEmail("");
      toast.success("Invite created");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const deleteUserMut = useMutation({
    mutationFn: (id: number) => deleteUser(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("User deleted");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const changeRoleMut = useMutation({
    mutationFn: ({ id, role }: { id: number; role: "admin" | "editor" | "viewer" }) =>
      changeRole(id, role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("Role updated");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold">Settings</h1>

        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
            <CardDescription>Your account details.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" value={user?.email ?? ""} disabled />
            </div>
            <div className="space-y-2">
              <Label htmlFor="name">Display name</Label>
              <Input id="name" placeholder="Your name" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Preferences</CardTitle>
            <CardDescription>
              Your timezone is the default for new schedules.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Label>Timezone</Label>
            <TimezoneSelect
              value={timezone}
              onChange={(tz) => timezoneMut.mutate(tz)}
              disabled={timezoneMut.isPending}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Security</CardTitle>
            <CardDescription>Change your password.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="pw">New password</Label>
              <Input id="pw" type="password" />
            </div>
            <Button>Update password</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System</CardTitle>
            <CardDescription>Instance-level settings.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="instance">Instance name</Label>
              <Input
                id="instance"
                value={instanceName}
                onChange={(e) => setInstanceName(e.target.value)}
              />
            </div>
            <Separator />
            <div className="space-y-2">
              <Button disabled>Save</Button>
              <p className="text-xs text-muted-foreground">
                System settings are not yet configurable from the UI.
              </p>
            </div>
          </CardContent>
        </Card>

        {isAdmin && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>Users</CardTitle>
                <CardDescription>Manage user roles and remove accounts.</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Email</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead className="w-32 text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(usersQuery.data ?? []).map((u) => (
                      <TableRow key={u.id}>
                        <TableCell>{u.email}</TableCell>
                        <TableCell>
                          <Select
                            value={u.role}
                            onValueChange={(role) =>
                              changeRoleMut.mutate({
                                id: u.id,
                                role: role as "admin" | "editor" | "viewer",
                              })
                            }
                          >
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {ROLES.map((r) => (
                                <SelectItem key={r} value={r}>
                                  {r}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => deleteUserMut.mutate(u.id)}
                          >
                            Delete
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Invite</CardTitle>
                <CardDescription>Create an invite for a new user.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2 md:col-span-2">
                    <Label htmlFor="invite-email">Email</Label>
                    <Input
                      id="invite-email"
                      type="email"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="invite-role">Role</Label>
                    <Select
                      value={inviteRole}
                      onValueChange={(v) => setInviteRole(v as "admin" | "editor" | "viewer")}
                    >
                      <SelectTrigger id="invite-role">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ROLES.map((r) => (
                          <SelectItem key={r} value={r}>
                            {r}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <Button
                  disabled={!inviteEmail || createInviteMut.isPending}
                  onClick={() => createInviteMut.mutate()}
                >
                  Create invite
                </Button>
                {lastInviteToken && (
                  <div className="space-y-2">
                    <Label>Invite token</Label>
                    <Input readOnly value={lastInviteToken} />
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Audit log</CardTitle>
                <CardDescription>Recent administrative actions.</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>When</TableHead>
                      <TableHead>Action</TableHead>
                      <TableHead>Resource</TableHead>
                      <TableHead>Meta</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(auditQuery.data ?? []).map((a) => (
                      <TableRow key={a.id}>
                        <TableCell>{new Date(a.at).toLocaleString()}</TableCell>
                        <TableCell>{a.action}</TableCell>
                        <TableCell>
                          {a.resource_type}
                          {a.resource_id !== null ? `#${a.resource_id}` : ""}
                        </TableCell>
                        <TableCell className="max-w-xs truncate">{a.meta_json}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </AppShell>
  );
}
