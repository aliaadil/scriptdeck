import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { LoginPage } from "@/auth/LoginPage";
import { SetupPage } from "@/auth/SetupPage";
import { Dashboard } from "@/pages/Dashboard";
import { Scripts } from "@/pages/Scripts";
import { ScriptEdit } from "@/pages/ScriptEdit";
import { Schedules } from "@/pages/Schedules";
import { Runs } from "@/pages/Runs";
import { RunView } from "@/pages/RunView";
import { Settings } from "@/pages/Settings";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/setup", element: <SetupPage /> },
  { element: <ProtectedRoute />, children: [
    { path: "/dashboard", element: <Dashboard /> },
    { path: "/scripts", element: <Scripts /> },
    { path: "/scripts/:id", element: <ScriptEdit /> },
    { path: "/schedules", element: <Schedules /> },
    { path: "/runs", element: <Runs /> },
    { path: "/runs/:id", element: <RunView /> },
    { element: <ProtectedRoute roles={["admin"]} />, children: [
      { path: "/settings", element: <Settings /> },
    ] },
  ] },
  { path: "*", element: <Navigate to="/dashboard" replace /> },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
