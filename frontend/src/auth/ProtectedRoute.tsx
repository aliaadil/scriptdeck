import { Navigate, Outlet } from "react-router-dom";
import { useAuth, type Role } from "./AuthProvider";

export function ProtectedRoute({ roles }: { roles?: Role[] }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-8 text-muted-foreground">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) {
    return <div className="p-8 text-destructive">Forbidden</div>;
  }
  return <Outlet />;
}
