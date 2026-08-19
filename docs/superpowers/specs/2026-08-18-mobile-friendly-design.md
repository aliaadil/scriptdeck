# Mobile-Friendly UI Tweaks

**Status:** approved (brainstorming gate cleared 2026-08-18)
**Branch:** `feature/mobile`
**Scope:** frontend only

## Goal

Make the Kindling UI usable on a phone. Sidebar disappears under 768px today with no replacement, so users cannot reach any navigation target. Goal is to (1) restore mobile navigation, (2) make the dashboard and run/log views readable on a narrow viewport, (3) give the scripting area list-page parity plus small editor layout fixes.

Editing code on a phone is not a target use case, so the editor stays as-is.

## Non-Goals

- Native app, PWA install, offline mode
- Major editor rewrite, mobile Monaco tweaks
- New design system, theme/dark-mode changes
- RTL, full a11y audit (a11y limited to ARIA on the new nav)

## Affected Pages

| Page | Change |
|---|---|
| Dashboard (`pages/Dashboard.tsx`) | Recent-runs table → card list on `< md` |
| Runs list (`pages/Runs.tsx`) | Table → card list on `< md` |
| Schedules list (`pages/Schedules.tsx`) | Table → card list on `< md` |
| Scripts list (`pages/Scripts.tsx`) | Table → card list on `< md` |
| RunView (`pages/RunView.tsx`) | Reduce paddings, wrap tabs, reflow header actions |
| ScriptEdit (`pages/ScriptEdit.tsx`) | Single-column stack, file list collapses into mobile control |
| ScriptNew + form-heavy pages | `w-full` inputs, full-width action rows on `< md` |
| AppShell + SiteHeader | Mount new `<MobileBottomNav />` on `< md` |

## Design

### 1. Mobile Navigation

New `<MobileBottomNav />` (`frontend/src/components/mobile-bottom-nav.tsx`), shown only when `useIsMobile()` is true.

- Four tabs: Dashboard, Scripts, Schedules, Runs.
- Each tab is `<NavLink>` with active style (matches sidebar active treatment) plus an `aria-current="page"`.
- Icons from `lucide-react` (same set as sidebar). Label under icon.
- `fixed inset-x-0 bottom-0 z-40`, `bg-background border-t`, `pb-[env(safe-area-inset-bottom)]`.
- Hidden ≥ md (`hidden md:hidden`).

Admin Settings:

- Not its own tab (keeps bar at 4).
- On `< md`, Settings link added inside the `UserMenu` dropdown — header already exists on both breakpoints.
- ≥ md, sidebar keeps its existing Settings entry.

AppShell change:

```tsx
<div className="flex min-h-screen bg-background text-foreground">
  <AppSidebar />
  <div className="flex flex-1 flex-col">
    <SiteHeader />
    <main className="flex-1 p-4 md:p-6 pb-20 md:pb-6">{children}</main>
  </div>
  <MobileBottomNav />
</div>
```

Extra bottom padding on `< main >` (`pb-20 md:pb-6`) reserves space above the fixed bar.

### 2. Card-List Pattern for Tables

Reusable shape — one component per page rather than a generic abstraction (avoids premature DRY). Each page already owns its table; mobile branch lives in the same file.

Rendering rule per page:

- If `useIsMobile()` → return card list.
- Else → return existing `<Table>` unchanged.

Card anatomy per page:

**Dashboard runs / Runs list:**

```
┌─────────────────────────────┐
│ script-name           [status]│
│ Started 2m ago · 3.2s         │
└─────────────────────────────┘
```

**Schedules:**

```
┌─────────────────────────────┐
│ schedule-name        [on/off]│
│ cron · next run in 12m       │
└─────────────────────────────┘
```

**Scripts:**

```
┌─────────────────────────────┐
│ script-name       [python]   │
│ last run: success · 4m ago   │
└─────────────────────────────┘
```

Cards are `<button>` or `<Link>` to the detail/edit/run page so the whole card is tappable. Use existing Card primitives or plain `<div>` with `rounded-md border p-3`.

Empty-state copy stays the same.

### 3. RunView Tweaks

- Wrapper padding `p-4 md:p-6` (was hardcoded `p-6`).
- `CardHeader` actions wrap to a new row when narrow — flex already handles it but verify Cancel button + status badge don't overflow on 360px.
- `TabsList` overflows horizontally on narrow; wrap it in `flex flex-wrap` so "Output / Config / Metadata" stack onto two rows at small widths. Trigger pills keep existing padding.
- Log `<pre>` already uses `whitespace-pre-wrap` — verified OK.

### 4. Scripting

**Scripts list:** card list as above.

**ScriptEdit:**

- File list (multi-file editor) collapses to a top `<Select>` or horizontal-scroll chip list on `< md`.
- Layout single-column: above-the-fold toolbar with Save stays visible. Existing flex layout already wraps — verify on narrow viewport.
- Touch targets: action buttons get `min-h-10` and adequate spacing.

**ScriptNew:**

- Inputs `w-full`.
- Submit button row full-width on `< md`, right-aligned on `≥ md`.

**Settings:** inputs full-width. Form rows stack.

## Component / File Plan

| Path | Action |
|---|---|
| `frontend/src/components/mobile-bottom-nav.tsx` | New |
| `frontend/src/components/AppShell.tsx` | Edit — mount nav, pad main |
| `frontend/src/components/user-menu.tsx` | Edit — surface Settings on `< md` |
| `frontend/src/pages/Dashboard.tsx` | Edit — card branch |
| `frontend/src/pages/Runs.tsx` | Edit — card branch |
| `frontend/src/pages/Schedules.tsx` | Edit — card branch |
| `frontend/src/pages/Scripts.tsx` | Edit — card branch |
| `frontend/src/pages/RunView.tsx` | Edit — pad/wrap |
| `frontend/src/pages/ScriptEdit.tsx` | Edit — collapse file picker on mobile |
| `frontend/src/pages/ScriptNew.tsx` | Edit — `w-full` form |
| `frontend/src/pages/Settings.tsx` | Edit — `w-full` form |

## Testing

- Existing unit + e2e tests must still pass (`vitest`, `playwright`).
- New unit tests (where reasonable, given timeline):
  - `<MobileBottomNav />` renders four links, hides ≥ md.
  - Card branches render the right data on `< md` (if a test util for viewport exists).
- Manual: open Chrome DevTools device toolbar. Verify iPhone 12 (390px), iPhone SE (375px), Pixel 5 (393px).
- Manual checks: bottom nav covers, log readability, editor file picker collapse, all-tap targets.

## Risks

- Tailwind's md breakpoint is 768px. `useIsMobile` uses 768 (`MOBILE_BREAKPOINT = 768`). Aligned.
- iOS safe area: use `pb-[env(safe-area-inset-bottom)]` on the nav and the `< main >` padding-tweak already pads it.
- Active-tab indicator matches sidebar logic (same active color).
- Admin Settings on mobile must still be discoverable — lives in UserMenu, add visible "Settings" item only when `< md && user.role === "admin"`.

## Out of Scope (explicit)

- Bottom-sheet menus
- Pull-to-refresh on log stream
- Pinch-to-zoom in editor
- Landscape-specific layouts
