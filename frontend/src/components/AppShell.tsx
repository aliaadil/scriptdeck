import { AppSidebar } from "./app-sidebar";
import { SiteHeader } from "./site-header";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AppSidebar />
      <div className="flex flex-1 flex-col">
        <SiteHeader />
        <main className="flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
