# UI Polish with Reui Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace barebones styling with a polished, component-driven UI using Reui via the shadcn registry, add system-aware dark mode, and rework the shell as a sidebar layout.

**Architecture:** Reui components copied into the repo via shadcn registry (`src/components/ui/*`). Tailwind CSS variables drive both light and dark themes. `next-themes` provides `class`-based theme switching with `system` default. Pages swap raw HTML for Reui primitives; layout changes to a fixed sidebar + sticky header.

**Tech Stack:** React 18, Vite 5, Tailwind 3.4, Reui (via shadcn registry), `next-themes`, `lucide-react`, Radix UI, `react-hook-form`, `zod`, `@tanstack/react-query`, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-16-ui-polish-reui-design.md`

## Global Constraints

- Node floor: existing project (`>=18.17`).
- Theme strategy: `class` on `<html>`, default `system`, `enableSystem: true`.
- All colors via Tailwind tokens mapped to CSS vars. No hex literals in components.
- Reui components live in `src/components/ui/` (shadcn) and `src/components/reui/*` (Reui-specific). Both follow alias `@/components`.
- No backend changes. No new deployment steps.
- Tests: every modified component with render logic gets a Vitest render test. Every page change updates Playwright e2e selectors.
- Commits: one per task. Conventional Commits. Co-authored by Claude.
- Caveman mode off in plan/code blocks. Commit messages and code normal.

## File Structure

**New files:**
- `frontend/src/components/theme-provider.tsx` — `next-themes` wrapper.
- `frontend/src/components/mode-toggle.tsx` — header dropdown.
- `frontend/src/components/app-sidebar.tsx` — left nav.
- `frontend/src/components/site-header.tsx` — top bar.
- `frontend/src/components/ui/*` — Reui primitives (button, input, label, card, badge, dropdown-menu, dialog, sheet, tabs, table, select, switch, field, form, sonner, empty, sidebar, command, popover, avatar, separator, tooltip, skeleton, pagination, data-table).
- `frontend/src/components/reui/data-table.tsx` — Reui table wrapper.
- `frontend/src/components/reui/empty.tsx` — empty state.
- `frontend/src/components/brand.tsx` — logo + name.
- `frontend/src/components/user-menu.tsx` — header dropdown for user.
- `frontend/src/lib/cn.ts` — already exists as `src/lib/utils.ts`; reuse.
- `frontend/src/components/__tests__/mode-toggle.test.tsx` — render test.
- `frontend/src/components/__tests__/theme-provider.test.tsx` — render test.
- `frontend/tests/e2e/visual.spec.ts` — Playwright visual snapshots.

**Modified files:**
- `frontend/components.json` — add Reui registry.
- `frontend/package.json` — add `next-themes`.
- `frontend/src/index.css` — full palette + `.dark` block.
- `frontend/tailwind.config.ts` — map colors + `darkMode: ["class"]`.
- `frontend/src/main.tsx` — wrap with `<ThemeProvider>`.
- `frontend/src/auth/LoginPage.tsx` — Reui primitives.
- `frontend/src/auth/SetupPage.tsx` — Reui primitives.
- `frontend/src/components/AppShell.tsx` — replaced by sidebar + header.
- `frontend/src/pages/Dashboard.tsx` — Card grid + Table.
- `frontend/src/pages/Scripts.tsx` — DataTable + Dialog.
- `frontend/src/pages/ScriptEdit.tsx` — Tabs + Card.
- `frontend/src/pages/Schedules.tsx` — DataTable + Switch.
- `frontend/src/pages/Runs.tsx` — DataTable + filters.
- `frontend/src/pages/RunView.tsx` — Card + Tabs.
- `frontend/src/pages/Settings.tsx` — Card sections.
- `frontend/tests/e2e/*` — selectors updated.

---

## Task 1: Add Reui registry + install next-themes

**Files:**
- Modify: `frontend/components.json`
- Modify: `frontend/package.json`

**Step 1.1: Add Reui registry to components.json**

Replace `frontend/components.json` with:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "reui",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "src/index.css",
    "baseColor": "slate",
    "cssVariables": true
  },
  "registries": {
    "@reui": {
      "url": "https://reui.io/r/{name}.json",
      "params": {
        "style": "new-york"
      }
    }
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils"
  }
}
```

- [ ] **Step 1.2: Install next-themes**

Run from `frontend/`:

```bash
npm install next-themes
```

Expected: `package.json` lists `next-themes`. `package-lock.json` updated.

- [ ] **Step 1.3: Verify install**

Run: `npm ls next-themes`
Expected: `next-themes@<version>`.

- [ ] **Step 1.4: Commit**

```bash
git add frontend/components.json frontend/package.json frontend/package-lock.json
git commit -m "chore(ui): add Reui registry and next-themes"
```

---

## Task 2: Full CSS palette + Tailwind config

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/tailwind.config.ts`

**Step 2.1: Replace index.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222 47% 11%;
    --card: 0 0% 100%;
    --card-foreground: 222 47% 11%;
    --popover: 0 0% 100%;
    --popover-foreground: 222 47% 11%;
    --primary: 221 83% 53%;
    --primary-foreground: 210 40% 98%;
    --secondary: 210 40% 96%;
    --secondary-foreground: 222 47% 11%;
    --muted: 210 40% 96%;
    --muted-foreground: 215 16% 47%;
    --accent: 210 40% 96%;
    --accent-foreground: 222 47% 11%;
    --destructive: 0 84% 60%;
    --destructive-foreground: 210 40% 98%;
    --success: 142 71% 45%;
    --success-foreground: 210 40% 98%;
    --warning: 38 92% 50%;
    --warning-foreground: 222 47% 11%;
    --border: 214 32% 91%;
    --input: 214 32% 91%;
    --ring: 221 83% 53%;
    --chart-1: 221 83% 53%;
    --chart-2: 142 71% 45%;
    --chart-3: 38 92% 50%;
    --chart-4: 280 65% 60%;
    --chart-5: 340 75% 55%;
    --sidebar: 0 0% 98%;
    --sidebar-foreground: 222 47% 11%;
    --sidebar-primary: 221 83% 53%;
    --sidebar-primary-foreground: 210 40% 98%;
    --sidebar-accent: 210 40% 96%;
    --sidebar-accent-foreground: 222 47% 11%;
    --sidebar-border: 214 32% 91%;
    --sidebar-ring: 221 83% 53%;
    --radius: 0.5rem;
  }

  .dark {
    --background: 222 47% 6%;
    --foreground: 210 40% 98%;
    --card: 222 47% 8%;
    --card-foreground: 210 40% 98%;
    --popover: 222 47% 8%;
    --popover-foreground: 210 40% 98%;
    --primary: 217 91% 60%;
    --primary-foreground: 222 47% 11%;
    --secondary: 217 33% 17%;
    --secondary-foreground: 210 40% 98%;
    --muted: 217 33% 17%;
    --muted-foreground: 215 20% 65%;
    --accent: 217 33% 17%;
    --accent-foreground: 210 40% 98%;
    --destructive: 0 63% 50%;
    --destructive-foreground: 210 40% 98%;
    --success: 142 71% 45%;
    --success-foreground: 210 40% 98%;
    --warning: 38 92% 50%;
    --warning-foreground: 222 47% 11%;
    --border: 217 33% 17%;
    --input: 217 33% 17%;
    --ring: 217 91% 60%;
    --chart-1: 217 91% 60%;
    --chart-2: 142 71% 45%;
    --chart-3: 38 92% 50%;
    --chart-4: 280 65% 60%;
    --chart-5: 340 75% 55%;
    --sidebar: 222 47% 8%;
    --sidebar-foreground: 210 40% 98%;
    --sidebar-primary: 217 91% 60%;
    --sidebar-primary-foreground: 222 47% 11%;
    --sidebar-accent: 217 33% 17%;
    --sidebar-accent-foreground: 210 40% 98%;
    --sidebar-border: 217 33% 17%;
    --sidebar-ring: 217 91% 60%;
  }
}

@layer base {
  * {
    border-color: hsl(var(--border));
  }
  body {
    background-color: hsl(var(--background));
    color: hsl(var(--foreground));
  }
}
```

- [ ] **Step 2.2: Replace tailwind.config.ts**

```ts
import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        chart: {
          1: "hsl(var(--chart-1))",
          2: "hsl(var(--chart-2))",
          3: "hsl(var(--chart-3))",
          4: "hsl(var(--chart-4))",
          5: "hsl(var(--chart-5))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [tailwindcssAnimate],
} satisfies Config;
```

- [ ] **Step 2.3: Build to verify config**

Run from `frontend/`:

```bash
npm run build
```

Expected: build succeeds. CSS contains `:root` and `.dark` blocks.

- [ ] **Step 2.4: Commit**

```bash
git add frontend/src/index.css frontend/tailwind.config.ts
git commit -m "feat(ui): full shadcn palette with light and dark mode"
```

---

## Task 3: ThemeProvider wrapper

**Files:**
- Create: `frontend/src/components/theme-provider.tsx`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/src/components/__tests__/theme-provider.test.tsx`

- [ ] **Step 3.1: Write failing test**

`frontend/src/components/__tests__/theme-provider.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ThemeProvider } from "../theme-provider";

describe("ThemeProvider", () => {
  it("renders children", () => {
    render(
      <ThemeProvider>
        <div data-testid="child">hello</div>
      </ThemeProvider>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3.2: Run test, expect fail**

Run: `npm test -- src/components/__tests__/theme-provider.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3.3: Create ThemeProvider**

`frontend/src/components/theme-provider.tsx`:

```tsx
import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ReactNode } from "react";

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {children}
    </NextThemesProvider>
  );
}
```

- [ ] **Step 3.4: Run test, expect pass**

Run: `npm test -- src/components/__tests__/theme-provider.test.tsx`
Expected: PASS.

- [ ] **Step 3.5: Wrap app in main.tsx**

Read `frontend/src/main.tsx`. Wrap the router children:

```tsx
import { ThemeProvider } from "@/components/theme-provider";
// ...
<ThemeProvider>
  <RouterProvider router={router} />
</ThemeProvider>
```

Verify file compiles.

- [ ] **Step 3.6: Run all tests**

Run: `npm test`
Expected: all pass.

- [ ] **Step 3.7: Commit**

```bash
git add frontend/src/components/theme-provider.tsx frontend/src/components/__tests__/theme-provider.test.tsx frontend/src/main.tsx
git commit -m "feat(ui): theme provider with system default"
```

---

## Task 4: Install Reui primitives

**Files:**
- Modify: `frontend/src/components/ui/*` (created via CLI)

- [ ] **Step 4.1: Initialize Reui**

Run from `frontend/`:

```bash
npx shadcn@latest init --force
```

When prompted: base color `slate`, CSS variables `yes`. Confirm overwrite of `index.css` only if asked — we already wrote it. If prompt offers to overwrite, decline (we keep our palette).

- [ ] **Step 4.2: Add Reui components**

Run from `frontend/`:

```bash
npx shadcn@latest add reui:button reui:input reui:label reui:textarea reui:card reui:badge reui:dropdown-menu reui:dialog reui:sheet reui:tabs reui:table reui:select reui:switch reui:field reui:form reui:sonner reui:empty reui:sidebar reui:command reui:popover reui:avatar reui:separator reui:tooltip reui:skeleton reui:pagination reui:checkbox reui:radio-group reui:slider reui:alert reui:accordion reui:breadcrumb reui:combobox reui:date-picker reui:data-table
```

Expected: files created under `src/components/ui/` and `src/components/reui/`.

- [ ] **Step 4.3: Verify build**

Run: `npm run build`
Expected: build succeeds, no missing imports.

- [ ] **Step 4.4: Commit**

```bash
git add frontend/src/components
git commit -m "feat(ui): install Reui primitive components"
```

---

## Task 5: ModeToggle

**Files:**
- Create: `frontend/src/components/mode-toggle.tsx`
- Create: `frontend/src/components/__tests__/mode-toggle.test.tsx`

- [ ] **Step 5.1: Write failing test**

`frontend/src/components/__tests__/mode-toggle.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ModeToggle } from "../mode-toggle";

describe("ModeToggle", () => {
  it("renders the toggle button", () => {
    render(<ModeToggle />);
    expect(screen.getByRole("button", { name: /toggle theme/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 5.2: Run test, expect fail**

Run: `npm test -- src/components/__tests__/mode-toggle.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 5.3: Create ModeToggle**

`frontend/src/components/mode-toggle.tsx`:

```tsx
import { Moon, Sun, Monitor } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function ModeToggle() {
  const { setTheme, theme } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Toggle theme">
          <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
          <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => setTheme("light")}>
          <Sun className="mr-2 h-4 w-4" /> Light
          {theme === "light" && <span className="ml-auto text-xs">✓</span>}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("dark")}>
          <Moon className="mr-2 h-4 w-4" /> Dark
          {theme === "dark" && <span className="ml-auto text-xs">✓</span>}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("system")}>
          <Monitor className="mr-2 h-4 w-4" /> System
          {theme === "system" && <span className="ml-auto text-xs">✓</span>}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
```

- [ ] **Step 5.4: Run test, expect pass**

Run: `npm test -- src/components/__tests__/mode-toggle.test.tsx`
Expected: PASS.

- [ ] **Step 5.5: Commit**

```bash
git add frontend/src/components/mode-toggle.tsx frontend/src/components/__tests__/mode-toggle.test.tsx
git commit -m "feat(ui): mode toggle dropdown"
```

---

## Task 6: Brand + UserMenu

**Files:**
- Create: `frontend/src/components/brand.tsx`
- Create: `frontend/src/components/user-menu.tsx`
- Create: `frontend/src/components/__tests__/user-menu.test.tsx`

- [ ] **Step 6.1: Write failing test**

`frontend/src/components/__tests__/user-menu.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { UserMenu } from "../user-menu";

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { email: "admin@example.com", role: "admin" },
    logout: vi.fn(),
  }),
}));

describe("UserMenu", () => {
  it("renders the user email", () => {
    render(<UserMenu />);
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6.2: Run test, expect fail**

Run: `npm test -- src/components/__tests__/user-menu.test.tsx`
Expected: FAIL.

- [ ] **Step 6.3: Create Brand**

`frontend/src/components/brand.tsx`:

```tsx
import { Link } from "react-router-dom";

export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <Link to="/dashboard" className="flex items-center gap-2 font-semibold">
      <div className="grid h-8 w-8 place-items-center rounded-md bg-primary text-primary-foreground">
        S
      </div>
      {!collapsed && <span className="text-base">ScriptDeck</span>}
    </Link>
  );
}
```

- [ ] **Step 6.4: Create UserMenu**

`frontend/src/components/user-menu.tsx`:

```tsx
import { useNavigate } from "react-router-dom";
import { LogOut, User as UserIcon } from "lucide-react";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

export function UserMenu() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  if (!user) return null;
  const initials = user.email.slice(0, 2).toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="gap-2 px-2">
          <Avatar className="h-7 w-7">
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>
          <span className="text-sm">{user.email}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <div className="flex flex-col">
            <span className="text-sm font-medium">{user.email}</span>
            <span className="text-xs text-muted-foreground">{user.role}</span>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => nav("/settings")}>
          <UserIcon className="mr-2 h-4 w-4" /> Profile
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={async () => {
            await logout();
            nav("/login");
          }}
        >
          <LogOut className="mr-2 h-4 w-4" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
```

- [ ] **Step 5: Run test, expect pass**

Run: `npm test -- src/components/__tests__/user-menu.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/brand.tsx frontend/src/components/user-menu.tsx frontend/src/components/__tests__/user-menu.test.tsx
git commit -m "feat(ui): brand and user menu"
```

---

## Task 7: AppSidebar + SiteHeader + AppShell

**Files:**
- Create: `frontend/src/components/app-sidebar.tsx`
- Create: `frontend/src/components/site-header.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/__tests__/app-shell.test.tsx`

- [ ] **Step 7.1: Write failing test**

`frontend/src/components/__tests__/app-shell.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { AppShell } from "../AppShell";

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { email: "admin@example.com", role: "admin" },
    logout: vi.fn(),
  }),
}));

describe("AppShell", () => {
  it("renders nav links", () => {
    render(
      <MemoryRouter>
        <AppShell>
          <div>child</div>
        </AppShell>
      </MemoryRouter>
    );
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Scripts")).toBeInTheDocument();
    expect(screen.getByText("Schedules")).toBeInTheDocument();
    expect(screen.getByText("Runs")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });
});
```

- [ ] **Step 7.2: Run test, expect fail**

Run: `npm test -- src/components/__tests__/app-shell.test.tsx`
Expected: FAIL — old structure doesn't have all required links.

- [ ] **Step 7.3: Create AppSidebar**

`frontend/src/components/app-sidebar.tsx`:

```tsx
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FileCode2,
  Calendar,
  Activity,
  Settings,
} from "lucide-react";
import { useAuth } from "@/auth/AuthProvider";
import { Brand } from "./brand";
import { cn } from "@/lib/utils";

const items = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/scripts", label: "Scripts", icon: FileCode2 },
  { to: "/schedules", label: "Schedules", icon: Calendar },
  { to: "/runs", label: "Runs", icon: Activity },
];

export function AppSidebar() {
  const { user } = useAuth();
  return (
    <aside className="hidden md:flex md:w-60 md:flex-col md:border-r md:bg-sidebar md:text-sidebar-foreground">
      <div className="flex h-14 items-center border-b border-sidebar-border px-4">
        <Brand />
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {items.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              )
            }
          >
            <it.icon className="h-4 w-4" />
            {it.label}
          </NavLink>
        ))}
        {user?.role === "admin" && (
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              )
            }
          >
            <Settings className="h-4 w-4" />
            Settings
          </NavLink>
        )}
      </nav>
    </aside>
  );
}
```

- [ ] **Step 7.4: Create SiteHeader**

`frontend/src/components/site-header.tsx`:

```tsx
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { ModeToggle } from "./mode-toggle";
import { UserMenu } from "./user-menu";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-background px-4 md:px-6">
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input placeholder="Search…" className="pl-8" />
      </div>
      <ModeToggle />
      <UserMenu />
    </header>
  );
}
```

- [ ] **Step 7.5: Replace AppShell**

`frontend/src/components/AppShell.tsx`:

```tsx
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
```

- [ ] **Step 7.6: Run test, expect pass**

Run: `npm test -- src/components/__tests__/app-shell.test.tsx`
Expected: PASS.

- [ ] **Step 7.7: Build verify**

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 7.8: Commit**

```bash
git add frontend/src/components/app-sidebar.tsx frontend/src/components/site-header.tsx frontend/src/components/AppShell.tsx frontend/src/components/__tests__/app-shell.test.tsx
git commit -m "feat(ui): sidebar shell with sticky header"
```

---

## Task 8: LoginPage polish

**Files:**
- Modify: `frontend/src/auth/LoginPage.tsx`
- Create: `frontend/src/auth/__tests__/LoginPage.test.tsx`

- [ ] **Step 8.1: Write failing test**

`frontend/src/auth/__tests__/LoginPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { LoginPage } from "../LoginPage";

vi.mock("../AuthProvider", () => ({
  useAuth: () => ({
    login: vi.fn().mockResolvedValue(undefined),
    user: null,
    logout: vi.fn(),
    setup: vi.fn(),
  }),
}));

describe("LoginPage", () => {
  it("renders form fields", () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    );
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 8.2: Run test, expect fail**

Run: `npm test -- src/auth/__tests__/LoginPage.test.tsx`
Expected: FAIL — old inputs lack `label` association.

- [ ] **Step 8.3: Replace LoginPage**

`frontend/src/auth/LoginPage.tsx`:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "@/components/ui/sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { useAuth } from "./AuthProvider";
import { Brand } from "@/components/brand";

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

export function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
  });

  async function onSubmit(values: z.infer<typeof schema>) {
    try {
      await login(values.email, values.password);
      nav("/dashboard");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-2 text-center">
          <div className="flex justify-center">
            <Brand />
          </div>
          <CardTitle>Welcome back</CardTitle>
          <CardDescription>Sign in to your ScriptDeck account.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="email">Email</FieldLabel>
                <Input id="email" type="email" {...register("email")} />
                {errors.email && <FieldError>{errors.email.message}</FieldError>}
              </Field>
              <Field>
                <FieldLabel htmlFor="password">Password</FieldLabel>
                <Input id="password" type="password" {...register("password")} />
                {errors.password && <FieldError>{errors.password.message}</FieldError>}
              </Field>
              <Button type="submit" disabled={isSubmitting} className="w-full">
                {isSubmitting ? "Signing in…" : "Sign in"}
              </Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
```

Note: `@hookform/resolvers` install check — if missing, run `npm install @hookform/resolvers`.

- [ ] **Step 8.4: Run test, expect pass**

Run: `npm test -- src/auth/__tests__/LoginPage.test.tsx`
Expected: PASS.

- [ ] **Step 8.5: Commit**

```bash
git add frontend/src/auth/LoginPage.tsx frontend/src/auth/__tests__/LoginPage.test.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat(ui): polish login page"
```

---

## Task 9: SetupPage polish

**Files:**
- Modify: `frontend/src/auth/SetupPage.tsx`
- Create: `frontend/src/auth/__tests__/SetupPage.test.tsx`

- [ ] **Step 9.1: Write failing test**

`frontend/src/auth/__tests__/SetupPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { SetupPage } from "../SetupPage";

vi.mock("../AuthProvider", () => ({
  useAuth: () => ({
    setup: vi.fn().mockResolvedValue(undefined),
    user: null,
    logout: vi.fn(),
    login: vi.fn(),
  }),
}));

describe("SetupPage", () => {
  it("renders form fields", () => {
    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>
    );
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create admin/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 9.2: Run test, expect fail**

Run: `npm test -- src/auth/__tests__/SetupPage.test.tsx`
Expected: FAIL.

- [ ] **Step 9.3: Replace SetupPage**

`frontend/src/auth/SetupPage.tsx`:

```tsx
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "@/components/ui/sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { useAuth } from "./AuthProvider";
import { Brand } from "@/components/brand";

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(8, "Password must be at least 8 characters"),
});

export function SetupPage() {
  const { setup } = useAuth();
  const nav = useNavigate();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
  });

  async function onSubmit(values: z.infer<typeof schema>) {
    try {
      await setup(values.email, values.password);
      nav("/dashboard");
    } catch (e) {
      const msg = e instanceof Error ? e.message : JSON.stringify(e);
      toast.error(msg);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-2 text-center">
          <div className="flex justify-center">
            <Brand />
          </div>
          <CardTitle>Welcome</CardTitle>
          <CardDescription>Create the first admin account.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="email">Email</FieldLabel>
                <Input id="email" type="email" {...register("email")} />
                {errors.email && <FieldError>{errors.email.message}</FieldError>}
              </Field>
              <Field>
                <FieldLabel htmlFor="password">Password (min 8)</FieldLabel>
                <Input id="password" type="password" {...register("password")} />
                {errors.password && <FieldError>{errors.password.message}</FieldError>}
              </Field>
              <Button type="submit" disabled={isSubmitting} className="w-full">
                {isSubmitting ? "Creating…" : "Create admin"}
              </Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 9.4: Run test, expect pass**

Run: `npm test -- src/auth/__tests__/SetupPage.test.tsx`
Expected: PASS.

- [ ] **Step 9.5: Commit**

```bash
git add frontend/src/auth/SetupPage.tsx frontend/src/auth/__tests__/SetupPage.test.tsx
git commit -m "feat(ui): polish setup page"
```

---

## Task 10: Dashboard polish

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/pages/__tests__/Dashboard.test.tsx`

- [ ] **Step 10.1: Write failing test**

`frontend/src/pages/__tests__/Dashboard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { Dashboard } from "../Dashboard";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ scripts: [], runs: [] }),
  },
}));

describe("Dashboard", () => {
  it("renders stat cards", async () => {
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    expect(await screen.findByText(/scripts/i)).toBeInTheDocument();
    expect(await screen.findByText(/schedules/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 10.2: Run test, expect fail**

Run: `npm test -- src/pages/__tests__/Dashboard.test.tsx`
Expected: FAIL — old dashboard lacks expected structure.

- [ ] **Step 10.3: Read existing implementation**

Open `frontend/src/pages/Dashboard.tsx`. Preserve data fetching logic. Replace markup.

- [ ] **Step 10.4: Replace Dashboard markup**

Keep the existing query logic and data hooks. Replace the body with:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

export function Dashboard() {
  const { data: scripts = [] } = useQuery({ queryKey: ["scripts"], queryFn: () => api.get("/scripts") });
  const { data: runs = [] } = useQuery({ queryKey: ["runs"], queryFn: () => api.get("/runs") });
  const { data: schedules = [] } = useQuery({ queryKey: ["schedules"], queryFn: () => api.get("/schedules") });
  const todayRuns = (runs as any[]).filter((r) => isToday(r.started_at));
  const failures = (runs as any[]).filter((r) => r.status === "failed").length;
  const failureRate = todayRuns.length ? Math.round((failures / todayRuns.length) * 100) : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Total scripts" value={(scripts as any[]).length} />
        <StatCard title="Active schedules" value={(schedules as any[]).filter((s: any) => s.enabled).length} />
        <StatCard title="Runs today" value={todayRuns.length} />
        <StatCard title="Failure rate" value={`${failureRate}%`} />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Script</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(runs as any[]).slice(0, 8).map((r: any) => (
                <TableRow key={r.id}>
                  <TableCell>{r.script_name}</TableCell>
                  <TableCell>
                    <Badge variant={r.status === "failed" ? "destructive" : r.status === "success" ? "success" : "secondary"}>
                      {r.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{new Date(r.started_at).toLocaleString()}</TableCell>
                  <TableCell>{r.duration}</TableCell>
                </TableRow>
              ))}
              {runs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground">
                    No runs yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({ title, value }: { title: string; value: number | string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold">{value}</div>
      </CardContent>
    </Card>
  );
}

function isToday(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}
```

- [ ] **Step 10.5: Run test, expect pass**

Run: `npm test -- src/pages/__tests__/Dashboard.test.tsx`
Expected: PASS.

- [ ] **Step 10.6: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/__tests__/Dashboard.test.tsx
git commit -m "feat(ui): dashboard with stats and recent runs"
```

---

## Task 11: Scripts page

**Files:**
- Modify: `frontend/src/pages/Scripts.tsx`
- Create: `frontend/src/pages/__tests__/Scripts.test.tsx`

- [ ] **Step 11.1: Write failing test**

`frontend/src/pages/__tests__/Scripts.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { Scripts } from "../Scripts";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue([]),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("Scripts", () => {
  it("renders page header", async () => {
    render(
      <MemoryRouter>
        <Scripts />
      </MemoryRouter>
    );
    expect(await screen.findByRole("heading", { name: /scripts/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new script/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 11.2: Run test, expect fail**

Run: `npm test -- src/pages/__tests__/Scripts.test.tsx`
Expected: FAIL.

- [ ] **Step 11.3: Read existing Scripts.tsx**

Preserve data fetching.

- [ ] **Step 11.4: Replace Scripts body**

```tsx
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/reui/empty";
import { toast } from "@/components/ui/sonner";
import { Plus } from "lucide-react";

export function Scripts() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data: scripts = [] } = useQuery({ queryKey: ["scripts"], queryFn: () => api.get("/scripts") });
  const run = useMutation({
    mutationFn: (id: string) => api.post(`/scripts/${id}/run`, {}),
    onSuccess: () => toast.success("Run started"),
    onError: (e: Error) => toast.error(e.message),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/scripts/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Script deleted");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Scripts</h1>
        <Button onClick={() => nav("/scripts/new")}>
          <Plus className="mr-2 h-4 w-4" /> New script
        </Button>
      </div>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Language</TableHead>
              <TableHead>Schedule</TableHead>
              <TableHead>Last run</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(scripts as any[]).map((s: any) => (
              <TableRow key={s.id}>
                <TableCell>
                  <Link to={`/scripts/${s.id}`} className="font-medium hover:underline">
                    {s.name}
                  </Link>
                </TableCell>
                <TableCell><Badge variant="secondary">{s.language}</Badge></TableCell>
                <TableCell>{s.schedule ?? "—"}</TableCell>
                <TableCell>{s.last_run ? new Date(s.last_run).toLocaleString() : "—"}</TableCell>
                <TableCell className="text-right space-x-2">
                  <Button size="sm" variant="outline" onClick={() => run.mutate(s.id)}>Run</Button>
                  <Button size="sm" variant="outline" onClick={() => nav(`/scripts/${s.id}`)}>Edit</Button>
                  <Button size="sm" variant="destructive" onClick={() => del.mutate(s.id)}>Delete</Button>
                </TableCell>
              </TableRow>
            ))}
            {scripts.length === 0 && (
              <TableRow>
                <TableCell colSpan={5}>
                  <Empty>
                    <EmptyHeader>
                      <EmptyTitle>No scripts yet</EmptyTitle>
                      <EmptyDescription>Create your first script to get started.</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
```

- [ ] **Step 11.5: Run test, expect pass**

Run: `npm test -- src/pages/__tests__/Scripts.test.tsx`
Expected: PASS.

- [ ] **Step 11.6: Commit**

```bash
git add frontend/src/pages/Scripts.tsx frontend/src/pages/__tests__/Scripts.test.tsx
git commit -m "feat(ui): scripts page with table and actions"
```

---

## Task 12: ScriptEdit page

**Files:**
- Modify: `frontend/src/pages/ScriptEdit.tsx`
- Create: `frontend/src/pages/__tests__/ScriptEdit.test.tsx`

- [ ] **Step 12.1: Write failing test**

`frontend/src/pages/__tests__/ScriptEdit.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { ScriptEdit } from "../ScriptEdit";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ id: "1", name: "test", language: "python", source: "" }),
    put: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("ScriptEdit", () => {
  it("renders tabs", async () => {
    render(
      <MemoryRouter initialEntries={["/scripts/1"]}>
        <Routes>
          <Route path="/scripts/:id" element={<ScriptEdit />} />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByRole("tab", { name: /editor/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /config/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 12.2: Run test, expect fail**

Run: `npm test -- src/pages/__tests__/ScriptEdit.test.tsx`
Expected: FAIL.

- [ ] **Step 12.3: Read existing ScriptEdit.tsx**

Preserve data fetching and Monaco wiring.

- [ ] **Step 12.4: Replace ScriptEdit body**

```tsx
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/sonner";
import { Save, Play, Trash2 } from "lucide-react";

export function ScriptEdit() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const isNew = id === "new";
  const { data: script } = useQuery({
    queryKey: ["script", id],
    queryFn: () => api.get(`/scripts/${id}`),
    enabled: !isNew,
  });
  const save = useMutation({
    mutationFn: (body: any) => (isNew ? api.post("/scripts", body) : api.put(`/scripts/${id}`, body)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Saved");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const run = useMutation({
    mutationFn: () => api.post(`/scripts/${id}/run`, {}),
    onSuccess: () => toast.success("Run started"),
    onError: (e: Error) => toast.error(e.message),
  });
  const del = useMutation({
    mutationFn: () => api.delete(`/scripts/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Deleted");
      nav("/scripts");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{isNew ? "New script" : script?.name ?? "Loading…"}</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => run.mutate()} disabled={isNew}>
            <Play className="mr-2 h-4 w-4" /> Run
          </Button>
          <Button onClick={() => save.mutate(script)} disabled={!script}>
            <Save className="mr-2 h-4 w-4" /> Save
          </Button>
          {!isNew && (
            <Button variant="destructive" onClick={() => del.mutate()}>
              <Trash2 className="mr-2 h-4 w-4" /> Delete
            </Button>
          )}
        </div>
      </div>
      <Tabs defaultValue="editor">
        <TabsList>
          <TabsTrigger value="editor">Editor</TabsTrigger>
          <TabsTrigger value="config">Config</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
        </TabsList>
        <TabsContent value="editor">
          <Card>
            <CardContent className="p-0">
              <Editor
                height="60vh"
                defaultLanguage={script?.language ?? "python"}
                value={script?.source ?? ""}
                theme="vs-dark"
                options={{ minimap: { enabled: false } }}
              />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="config">
          <Card>
            <CardContent className="space-y-4 pt-6">
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" defaultValue={script?.name} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="desc">Description</Label>
                <Textarea id="desc" defaultValue={script?.description} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="logs">
          <Card>
            <CardContent className="font-mono text-xs">
              <pre>Run the script to see logs.</pre>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 12.5: Run test, expect pass**

Run: `npm test -- src/pages/__tests__/ScriptEdit.test.tsx`
Expected: PASS.

- [ ] **Step 12.6: Commit**

```bash
git add frontend/src/pages/ScriptEdit.tsx frontend/src/pages/__tests__/ScriptEdit.test.tsx
git commit -m "feat(ui): script edit page with tabs"
```

---

## Task 13: Schedules page

**Files:**
- Modify: `frontend/src/pages/Schedules.tsx`
- Create: `frontend/src/pages/__tests__/Schedules.test.tsx`

- [ ] **Step 13.1: Write failing test**

`frontend/src/pages/__tests__/Schedules.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { Schedules } from "../Schedules";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue([]),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe("Schedules", () => {
  it("renders header", async () => {
    render(
      <MemoryRouter>
        <Schedules />
      </MemoryRouter>
    );
    expect(await screen.findByRole("heading", { name: /schedules/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 13.2: Run test, expect fail**

Run: `npm test -- src/pages/__tests__/Schedules.test.tsx`
Expected: FAIL.

- [ ] **Step 13.3: Read existing Schedules.tsx**

Preserve data fetching.

- [ ] **Step 13.4: Replace Schedules body**

```tsx
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { Plus } from "lucide-react";
import { toast } from "@/components/ui/sonner";

export function Schedules() {
  const qc = useQueryClient();
  const { data: schedules = [] } = useQuery({ queryKey: ["schedules"], queryFn: () => api.get("/schedules") });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.put(`/schedules/${id}`, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Schedules</h1>
        <Button>
          <Plus className="mr-2 h-4 w-4" /> New schedule
        </Button>
      </div>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Cron</TableHead>
              <TableHead>Script</TableHead>
              <TableHead>Enabled</TableHead>
              <TableHead>Last run</TableHead>
              <TableHead>Next run</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(schedules as any[]).map((s: any) => (
              <TableRow key={s.id}>
                <TableCell className="font-mono text-xs">{s.cron}</TableCell>
                <TableCell>{s.script_name}</TableCell>
                <TableCell>
                  <Switch checked={s.enabled} onCheckedChange={(v) => toggle.mutate({ id: s.id, enabled: v })} />
                </TableCell>
                <TableCell>{s.last_run ? new Date(s.last_run).toLocaleString() : "—"}</TableCell>
                <TableCell>{s.next_run ? new Date(s.next_run).toLocaleString() : "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
```

- [ ] **Step 13.5: Run test, expect pass**

Run: `npm test -- src/pages/__tests__/Schedules.test.tsx`
Expected: PASS.

- [ ] **Step 13.6: Commit**

```bash
git add frontend/src/pages/Schedules.tsx frontend/src/pages/__tests__/Schedules.test.tsx
git commit -m "feat(ui): schedules page with toggle"
```

---

## Task 14: Runs page

**Files:**
- Modify: `frontend/src/pages/Runs.tsx`
- Create: `frontend/src/pages/__tests__/Runs.test.tsx`

- [ ] **Step 14.1: Write failing test**

`frontend/src/pages/__tests__/Runs.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { Runs } from "../Runs";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue([]) },
}));

describe("Runs", () => {
  it("renders header", async () => {
    render(
      <MemoryRouter>
        <Runs />
      </MemoryRouter>
    );
    expect(await screen.findByRole("heading", { name: /runs/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 14.2: Run test, expect fail**

Run: `npm test -- src/pages/__tests__/Runs.test.tsx`
Expected: FAIL.

- [ ] **Step 14.3: Read existing Runs.tsx**

Preserve data fetching.

- [ ] **Step 14.4: Replace Runs body**

```tsx
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function Runs() {
  const nav = useNavigate();
  const [status, setStatus] = useState<string>("all");
  const { data: runs = [] } = useQuery({
    queryKey: ["runs", status],
    queryFn: () => api.get(status === "all" ? "/runs" : `/runs?status=${status}`),
  });
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Runs</h1>
      <div className="flex gap-3">
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="success">Success</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
            <SelectItem value="running">Running</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Run</TableHead>
              <TableHead>Script</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Exit</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(runs as any[]).map((r: any) => (
              <TableRow key={r.id} onClick={() => nav(`/runs/${r.id}`)} className="cursor-pointer">
                <TableCell className="font-mono text-xs">{r.id.slice(0, 8)}</TableCell>
                <TableCell>{r.script_name}</TableCell>
                <TableCell>
                  <Badge variant={r.status === "failed" ? "destructive" : r.status === "success" ? "success" : "secondary"}>
                    {r.status}
                  </Badge>
                </TableCell>
                <TableCell>{new Date(r.started_at).toLocaleString()}</TableCell>
                <TableCell>{r.duration}</TableCell>
                <TableCell>{r.exit_code}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
```

- [ ] **Step 14.5: Run test, expect pass**

Run: `npm test -- src/pages/__tests__/Runs.test.tsx`
Expected: PASS.

- [ ] **Step 14.6: Commit**

```bash
git add frontend/src/pages/Runs.tsx frontend/src/pages/__tests__/Runs.test.tsx
git commit -m "feat(ui): runs page with status filter"
```

---

## Task 15: RunView page

**Files:**
- Modify: `frontend/src/pages/RunView.tsx`
- Create: `frontend/src/pages/__tests__/RunView.test.tsx`

- [ ] **Step 15.1: Write failing test**

`frontend/src/pages/__tests__/RunView.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { RunView } from "../RunView";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({ id: "abc", script_name: "test", status: "success", output: "" }) },
}));

describe("RunView", () => {
  it("renders tabs", async () => {
    render(
      <MemoryRouter initialEntries={["/runs/abc"]}>
        <Routes>
          <Route path="/runs/:id" element={<RunView />} />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByRole("tab", { name: /output/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 15.2: Run test, expect fail**

Run: `npm test -- src/pages/__tests__/RunView.test.tsx`
Expected: FAIL.

- [ ] **Step 15.3: Read existing RunView.tsx**

Preserve data fetching.

- [ ] **Step 15.4: Replace RunView body**

```tsx
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";

export function RunView() {
  const { id } = useParams();
  const { data: run } = useQuery({ queryKey: ["run", id], queryFn: () => api.get(`/runs/${id}`) });
  if (!run) return <div>Loading…</div>;
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>{run.script_name}</CardTitle>
            <p className="text-sm text-muted-foreground">Run {run.id.slice(0, 8)}</p>
          </div>
          <Badge variant={run.status === "failed" ? "destructive" : run.status === "success" ? "success" : "secondary"}>
            {run.status}
          </Badge>
        </CardHeader>
        <CardContent className="grid gap-4 text-sm sm:grid-cols-3">
          <Field label="Started" value={new Date(run.started_at).toLocaleString()} />
          <Field label="Duration" value={run.duration} />
          <Field label="Exit code" value={run.exit_code} />
        </CardContent>
      </Card>
      <Tabs defaultValue="output">
        <TabsList>
          <TabsTrigger value="output">Output</TabsTrigger>
          <TabsTrigger value="config">Config</TabsTrigger>
          <TabsTrigger value="metadata">Metadata</TabsTrigger>
        </TabsList>
        <TabsContent value="output">
          <Card>
            <CardContent className="bg-muted p-4 font-mono text-xs">
              <pre className="whitespace-pre-wrap">{run.output || "No output."}</pre>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="config">
          <Card>
            <CardContent className="text-sm">{JSON.stringify(run.config ?? {}, null, 2)}</CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="metadata">
          <Card>
            <CardContent className="text-sm">{JSON.stringify(run.metadata ?? {}, null, 2)}</CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}
```

- [ ] **Step 15.5: Run test, expect pass**

Run: `npm test -- src/pages/__tests__/RunView.test.tsx`
Expected: PASS.

- [ ] **Step 15.6: Commit**

```bash
git add frontend/src/pages/RunView.tsx frontend/src/pages/__tests__/RunView.test.tsx
git commit -m "feat(ui): run view with tabs"
```

---

## Task 16: Settings page

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Create: `frontend/src/pages/__tests__/Settings.test.tsx`

- [ ] **Step 16.1: Write failing test**

`frontend/src/pages/__tests__/Settings.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { Settings } from "../Settings";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({}), put: vi.fn() },
}));

describe("Settings", () => {
  it("renders sections", () => {
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    );
    expect(screen.getByText(/profile/i)).toBeInTheDocument();
    expect(screen.getByText(/security/i)).toBeInTheDocument();
    expect(screen.getByText(/system/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 16.2: Run test, expect fail**

Run: `npm test -- src/pages/__tests__/Settings.test.tsx`
Expected: FAIL.

- [ ] **Step 16.3: Read existing Settings.tsx**

Preserve data fetching.

- [ ] **Step 16.4: Replace Settings body**

```tsx
import { useAuth } from "@/auth/AuthProvider";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export function Settings() {
  const { user } = useAuth();
  return (
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
            <Input id="instance" placeholder="ScriptDeck" />
          </div>
          <Separator />
          <Button>Save</Button>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 16.5: Run test, expect pass**

Run: `npm test -- src/pages/__tests__/Settings.test.tsx`
Expected: PASS.

- [ ] **Step 16.6: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/pages/__tests__/Settings.test.tsx
git commit -m "feat(ui): settings page with sections"
```

---

## Task 17: Playwright e2e updates

**Files:**
- Modify: `frontend/tests/e2e/*`
- Create: `frontend/tests/e2e/visual.spec.ts`

- [ ] **Step 17.1: List existing e2e tests**

Run: `ls frontend/tests/e2e/`
Expected: snapshot of current specs.

- [ ] **Step 17.2: Update selectors**

For each existing spec, replace bare `input[type="email"]` with `getByLabel(/email/i)`. Replace `button:has-text("Sign in")` with `getByRole("button", { name: /sign in/i })`. Keep existing assertions.

- [ ] **Step 17.3: Add visual snapshot spec**

`frontend/tests/e2e/visual.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test("login page renders", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveScreenshot("login.png", { fullPage: true });
});

test("dashboard renders after login", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("admin@example.com");
  await page.getByLabel(/password/i).fill("password123");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard");
  await expect(page).toHaveScreenshot("dashboard.png", { fullPage: true });
});

test("dark mode toggle", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /toggle theme/i }).click();
  await page.getByRole("menuitem", { name: /dark/i }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
});
```

- [ ] **Step 17.4: Run e2e**

Run: `npm run test:e2e`
Expected: all pass.

- [ ] **Step 17.5: Commit**

```bash
git add frontend/tests/e2e
git commit -m "test(ui): update e2e selectors and add visual snapshots"
```

---

## Task 18: Final build + manual review

**Step 18.1: Run full vitest suite**

Run: `npm test`
Expected: all pass.

- [ ] **Step 18.2: Run full e2e suite**

Run: `npm run test:e2e`
Expected: all pass.

- [ ] **Step 18.3: Build production**

Run: `npm run build`
Expected: build succeeds, no warnings about missing exports.

- [ ] **Step 18.4: Manual smoke test**

Run: `npm run dev`
Visit `http://localhost:5173`:
- Toggle theme (light / dark / system)
- Navigate to each page
- Resize to mobile — sidebar hides, hamburger appears
- Tab through interactive elements — focus rings visible

- [ ] **Step 18.5: Commit any final tweaks**

Commit. If no changes, skip.

- [ ] **Step 18.6: Open PR**

Branch: `feat/ui-upgrade`
PR base: `main`
Body: link spec + plan.

---

## Self-Review

Spec coverage check:
- Reui install via registry → Task 1, 4 ✓
- next-themes → Task 1, 3 ✓
- Full CSS palette → Task 2 ✓
- Theme provider + system default → Task 3 ✓
- Mode toggle → Task 5 ✓
- Sidebar shell → Task 7 ✓
- Login + Setup polish → Task 8, 9 ✓
- Dashboard → Task 10 ✓
- Scripts/Schedules/Runs pages → Task 11, 13, 14 ✓
- ScriptEdit/RunView tabs → Task 12, 15 ✓
- Settings sections → Task 16 ✓
- toasts for errors → Tasks 8–16 ✓
- a11y (focus rings, aria-label) → Task 5, 7 ✓
- Vitest per component → Tasks 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 ✓
- Playwright updates + visual snapshots → Task 17 ✓
- Rollout order follows spec → Tasks 1→2→3→4→5→6→7→8…→18 ✓

Placeholder scan: no TBDs, no "etc.", no "similar to".

Type consistency:
- `useAuth()` returns `{ user, login, logout, setup }` — matches Tasks 6, 8, 9 ✓
- `api.get/post/put/delete` paths used in Tasks 10–16 match existing API conventions ✓
- `login(email, password)` and `setup(email, password)` signatures match existing AuthProvider ✓
- `Field` / `FieldGroup` / `FieldLabel` / `FieldError` consistent across Tasks 8, 9 ✓
- `Card` / `CardHeader` / `CardTitle` / `CardContent` / `CardDescription` consistent ✓
- `toast.success` / `toast.error` from `@/components/ui/sonner` — consistent ✓

No gaps. No placeholders.
