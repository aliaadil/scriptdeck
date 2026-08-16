# UI Polish with Reui — Design

Date: 2026-08-16
Status: Approved (verbal)
Owner: frontend

## Goal

Replace barebones hand-rolled styling with a coherent, polished UI. Add dark mode that follows system preference. Standardize on Reui components installed via the shadcn registry. Improve login, setup, and dashboard pages so the product feels finished.

## Non-goals

- No backend changes.
- No RBAC refactor.
- No new pages or features.
- No i18n.
- No new deployment process.

## Stack

- Framework: React 18 + Vite (existing).
- Styling: Tailwind 3.4 (existing).
- Component source: Reui, installed via shadcn registry.
- Icons: `lucide-react` (existing).
- Theme management: `next-themes`.
- Forms: `react-hook-form` + `zod` (existing).
- Server state: `@tanstack/react-query` (existing).
- Animation: `tailwindcss-animate` (existing, keep unless Reui ships its own — decide during install).

Reui installs as copied source files under `src/components/ui/` and `src/components/reui/`, themed through the same Tailwind CSS variables as shadcn. Reui registry is added to `components.json` so the existing `npx shadcn@latest add` workflow pulls Reui components too.

## Theming

### CSS variables

`frontend/src/index.css` defines the full shadcn palette in `:root` (light) and `.dark` (dark). Both blocks scoped under the class strategy so `next-themes` can toggle by adding/removing `.light` / `.dark` on `<html>`.

Variables defined:

- Surfaces: `--background`, `--foreground`, `--card`, `--card-foreground`, `--popover`, `--popover-foreground`.
- Brand: `--primary`, `--primary-foreground`, `--secondary`, `--secondary-foreground`, `--accent`, `--accent-foreground`.
- Neutrals: `--muted`, `--muted-foreground`.
- Status: `--destructive`, `--destructive-foreground`, `--success`, `--success-foreground`, `--warning`, `--warning-foreground`.
- Borders: `--border`, `--input`, `--ring`.
- Charts: `--chart-1` through `--chart-5`.
- Sidebar: `--sidebar`, `--sidebar-foreground`, `--sidebar-primary`, `--sidebar-primary-foreground`, `--sidebar-accent`, `--sidebar-accent-foreground`, `--sidebar-border`, `--sidebar-ring`.

All values in HSL space, matching shadcn defaults. Slate base color from `components.json` stays.

### Tailwind config

`tailwind.config.ts` maps every var under `theme.extend.colors`. Token form: `bg-background`, `text-foreground`, `border-border`, `bg-primary`, etc. Charts and sidebar get explicit token names.

`darkMode: ["class"]` set so `.dark` class activates dark vars.

### Theme provider

`src/components/theme-provider.tsx`:

```tsx
import { ThemeProvider as NextThemesProvider } from "next-themes";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
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

Wrap `<RouterProvider>` in `main.tsx`.

### Mode toggle

`src/components/mode-toggle.tsx`: Radix DropdownMenu with three items (Light, Dark, System). Icon swaps Sun/Moon/Monitor. Lives in the header.

## Shell layout

Replace `AppShell` with a Reui-style layout:

- **Sidebar** (left, `lg:` fixed width `240px`, `md:` collapsed to icons `64px`, below `md` replaced by `Sheet` drawer triggered from a burger button).
  - Groups: Dashboard, Scripts, Schedules, Runs, Settings (admin only).
  - Active route highlighted with `--sidebar-accent` background.
  - Logo + brand name at top.
- **Header** (top, sticky):
  - Search input (placeholder, no wiring yet).
  - Mode toggle.
  - User menu (Radix DropdownMenu): email, role, sign out.

Both `useAuth()` and `useTheme()` consumed inside the shell.

## Page-by-page changes

### LoginPage, SetupPage

- Centered `Card` on `bg-muted`.
- Brand mark top of card.
- `Field` (Reui) wrapping `Label` + `Input` + error message.
- `Button` (full width, loading state via `disabled` + spinner).
- Submit text: "Sign in" / "Create admin".
- Validation messages from `react-hook-form` + `zod`.

### Dashboard

- Top row: 4 `Card` stats (Total scripts, Active schedules, Runs today, Failure rate).
- Middle: `Card` with `Table` of recent runs (status `Badge`, time, duration, exit code).
- Bottom: `Card` with quick actions (New script, New schedule).

### Scripts

- Page header: title + "New script" `Button`.
- `DataTable` (Reui) with columns: Name, Language, Schedule, Last run, Actions.
- Row actions: Edit, Run now, Delete.
- Empty state: `Empty` component with CTA.

### ScriptEdit

- `Tabs`: Editor / Config / Logs.
- Editor: existing `@monaco-editor/react` wrapped in `Card`.
- Config: `Input`/`Select`/`Textarea` fields via `react-hook-form`.
- Logs: streamed output (existing).
- Footer: Save, Run, Delete buttons.

### Schedules

- Page header with "New schedule" `Button` → `Dialog` form.
- `DataTable`: Cron, Script, Enabled (`Switch`), Last run, Next run, Actions.
- `Switch` toggles enabled inline.

### Runs

- Filter bar: status `Select`, script `Select`, date range.
- `DataTable`: Run ID, Script, Status (`Badge`), Started, Duration, Exit code.
- Row click → RunView.

### RunView

- Header `Card`: status `Badge`, script, started, duration, exit code.
- `Tabs`: Output / Config / Metadata.
- Output: terminal-styled block.

### Settings

- `Card` sections: Profile, Security, System.
- Profile: email (read-only), display name `Input`.
- Security: change password form.
- System: instance name `Input`, Save button.

## Components to install

From Reui registry (via `npx shadcn@latest add reui:<name>`):

- `button`, `input`, `label`, `textarea`, `select`, `checkbox`, `switch`, `radio-group`, `slider`, `separator`, `card`, `badge`, `alert`, `skeleton`, `tabs`, `accordion`, `dialog`, `sheet`, `dropdown-menu`, `tooltip`, `popover`, `command`, `toast`, `form`, `field`, `data-table`, `table`, `pagination`, `empty`, `sidebar`, `avatar`, `breadcrumb`, `combobox`, `date-picker`, `sonner` (toast).

Each is a one-line add. Order of install documented in the implementation plan.

## State and data flow

- Pages continue to fetch via `react-query` (existing).
- Forms use `react-hook-form` + `zod` (existing).
- Auth state via `useAuth()` (existing).
- Theme via `useTheme()` from `next-themes`.
- No new global state.

## Error handling

- Async errors → `sonner` toast (Reui). Replace inline `setError` in LoginPage/SetupPage.
- Form validation errors → `Field` error message.
- Network errors → toast + retry button on failed mutations.
- 401 → existing auth flow (redirect to /login).

## Accessibility

- All interactive elements reachable via keyboard.
- Focus rings use `--ring`.
- Color contrast meets WCAG AA in both themes.
- Icon-only buttons have `aria-label`.
- Theme toggle announces state to screen readers via `aria-pressed`.

## Testing

- Vitest: snapshot `ModeToggle`, render tests for `Field`, `Card`.
- Playwright: update existing e2e selectors; add visual snapshots for `/login`, `/dashboard`. Both light and dark.
- Manual: keyboard nav pass, mobile viewport pass (sidebar → sheet).

## Files touched

- New: `src/components/theme-provider.tsx`, `src/components/mode-toggle.tsx`, `src/components/ui/*` (Reui copies), `src/components/reui/*` (Reui-specific bits).
- Modified: `src/index.css`, `tailwind.config.ts`, `components.json`, `src/main.tsx`, `src/auth/LoginPage.tsx`, `src/auth/SetupPage.tsx`, `src/components/AppShell.tsx`, `src/pages/*`.
- Tests: `tests/e2e/*`, `src/components/__tests__/*`.

No backend changes. No CI changes.

## Rollout

1. Install Reui registry + add `next-themes`.
2. Update CSS variables + Tailwind config.
3. Wrap app in `ThemeProvider`.
4. Build `ModeToggle` + add to header.
5. Replace `AppShell` with sidebar layout.
6. Sweep pages one by one, swapping raw HTML for primitives.
7. Update tests.
8. Visual review in both themes.
