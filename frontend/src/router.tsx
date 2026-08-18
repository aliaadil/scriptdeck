import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { LoginPage } from "@/auth/LoginPage";
import { SetupPage } from "@/auth/SetupPage";
import { Dashboard } from "@/pages/Dashboard";
import { Scripts } from "@/pages/Scripts";
import { ScriptEdit } from "@/pages/ScriptEdit";
import { ScriptNew } from "@/pages/ScriptNew";
import { Schedules } from "@/pages/Schedules";
import { Runs } from "@/pages/Runs";
import { RunView } from "@/pages/RunView";
import { Settings } from "@/pages/Settings";
import { NotFound } from "@/pages/NotFound";

const router = createBrowserRouter([
  { path: "/kindling/*", element: <ProtectedRoute />, children: [
    { path: "dashboard", element: <Dashboard /> },
    { path: "scripts", element: <Scripts /> },
    // Static segment must be declared before the dynamic one for readability;
    // react-router ranks static routes higher regardless of order.
    { path: "scripts/new", element: <ScriptNew /> },
    { path: "scripts/:id", element: <ScriptEdit /> },
    { path: "schedules", element: <Schedules /> },
    { path: "runs", element: <Runs /> },
    { path: "runs/:id", element: <RunView /> },
    { path: "settings", element: <Settings /> },
  ] },
  { path: "/kindling", element: <Navigate to="/kindling/dashboard" replace /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/setup", element: <SetupPage /> },
  // Show an explicit 404 instead of silently bouncing every unknown path to
  // /kindling/dashboard. The brief for this fix flagged that the catch-all
  // was hiding navigation-target mismatches.
  { path: "*", element: <NotFound /> },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
