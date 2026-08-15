import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export function SetupPage() {
  const { setup } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await setup(email, password);
      nav("/dashboard");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted">
      <form onSubmit={onSubmit} className="w-96 rounded-lg border bg-background p-8 shadow-sm">
        <h1 className="mb-2 text-2xl font-semibold">Welcome</h1>
        <p className="mb-6 text-sm text-muted-foreground">
          Create the first admin account.
        </p>
        <label className="mb-2 block text-sm font-medium">Email</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mb-4 w-full rounded border px-3 py-2"
        />
        <label className="mb-2 block text-sm font-medium">Password (min 8)</label>
        <input
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mb-4 w-full rounded border px-3 py-2"
        />
        {error && <div className="mb-4 text-sm text-destructive">{error}</div>}
        <button type="submit" className="w-full rounded bg-primary px-4 py-2 text-primary-foreground">
          Create admin
        </button>
      </form>
    </div>
  );
}
