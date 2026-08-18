# Task 11 Report — ScriptEdit rewrite + entrypoint picker + routing

**Status: DONE_WITH_CONCERNS**

> Note: this file previously held a stale report from the unrelated `feat-rebranding`
> branch's Task 11 (CI grep gate). Overwritten with the current task's report.

## What changed

| File | Change |
|---|---|
| `frontend/src/pages/ScriptEdit.tsx` | Full rewrite: FileTree + EditorPanel + FileDialog, entrypoint picker, Logs tab preserved |
| `frontend/src/router.tsx` | Added `scripts/new` → `<ScriptNew />` |
| `frontend/src/api/scripts.ts` | Added `updateScript(id, body)`; `updateScriptEntrypoint` now delegates to it |
| `frontend/src/pages/ScriptNew.tsx` | Fixed post-create redirect (see Deviation 1) |
| `frontend/src/pages/__tests__/ScriptEdit.test.tsx` | Rewritten: 9 tests |
| `frontend/src/pages/__tests__/ScriptNew.test.tsx` | Updated nav assertion; added vitest global imports |
| `frontend/src/components/editor/__tests__/QuickStartCards.test.tsx` | Added vitest global imports |

## New ScriptEdit layout

Header (name, `language · entrypoint: X`, Run, Delete) over three tabs:

- **Editor** — `FileTree` (left) + `EditorPanel` (right, autosaves via the Task 9 debounce).
  Default selection is the entrypoint, falling back to the first file. `FileDialog` for add;
  delete is confirm-gated. Empty state when no file is selected.
- **Config** — Name, Language (read-only), Entrypoint `<select data-testid="entrypoint-select">`,
  Description, and a Save button wired to `updateScript`.
- **Logs** — preserved verbatim from the original: `RunStatusBadge`, 1 s run polling,
  log fetch from `/runs/:id/log`, terminal-status toasts. Running a script auto-switches here.

## Deviations from the brief (all deliberate)

1. **Routes live under `/kindling`.** The brief said add `/scripts/new`, but every real route is
   nested under `/kindling/*`. Added `scripts/new` to that children array, so the effective path
   is `/kindling/scripts/new` — exactly what `Scripts.tsx` already links to. Consequently
   `ScriptNew.tsx` navigating to `/scripts/${id}` after create was a **live bug** (it would have
   hit the `*` NotFound catch-all); fixed to `/kindling/scripts/${id}` and updated its test.
   Same reasoning for the delete redirect (`/kindling/scripts`).
2. **Logs tab preserved** as instructed, including the Run mutation's `RunInfo` typing and the
   controlled `activeTab` (the brief's uncontrolled `defaultValue="editor"` Tabs cannot
   auto-switch on run).
3. **Config Name/Description use local state + an explicit Save button**, not a PUT per keystroke
   as the brief's `onChange` sketch implied.
4. **`activeLang` is a `useMemo`,** not state + effect — same result without a one-render lag on
   the language handed to Monaco.
5. **`del.onSuccess` tautology removed.** The brief's `if (activePath === activePath)` is always
   true; wrote `if (activePath === path)`, so deleting a *non-active* file no longer blows away
   the current selection. Deleting the active file still clears it and the default-selection
   effect immediately re-picks a neighbour — which incidentally resolves the no-op the brief
   flagged as harmless.
6. **File-content load is race-guarded** with a `cancelled` flag, so a slow response for a
   previously-selected file can't overwrite the current one. Load failures now surface a toast
   instead of silently blanking the editor.
7. **Entrypoint options** include `.ts/.mjs/.cjs` beyond the brief's `.py/.js/.sh`, plus the
   current entrypoint even if its extension is unusual — otherwise the `<select>` could render
   with a value absent from its option list.

## Tests

`frontend/src/pages/__tests__/ScriptEdit.test.tsx` — 9 tests: three tabs render; tree lists all
files incl. directory grouping; entrypoint opens by default with content loaded; clicking a tree
file loads it; entrypoint select fires `updateScriptEntrypoint`; add dialog calls
`createScriptFile`; delete calls `deleteScriptFile` after confirm; Config Save calls
`updateScript`; Run posts and switches to the Logs tab.

Note for future test authors: Radix `TabsContent` **unmounts** inactive panels, so Config/Logs
assertions must click the tab first.

## Verification

- `npx vitest run src/pages/__tests__/ScriptEdit.test.tsx` → 9/9 pass
- `npx vitest run` → **61/61 pass across 22 files**
- `npx tsc --noEmit` → clean
- `npx eslint` on touched files → clean
- `npm run build` → succeeds

## Concerns

1. **Out-of-scope fix (pre-existing breakage).** `npm run build` runs `tsc --noEmit`, and Task 10
   left 10 type errors in `QuickStartCards.test.tsx` / `ScriptNew.test.tsx` (vitest globals used
   without imports — vitest ran fine, tsc did not). Verified against a stash that these predate
   this task. Fixed with two import lines because the branch build was red.
2. **Upload is a stub.** `FileTree`'s `onUpload` toasts "coming in a later release", per the
   brief's `TODO: upload in v2.1`. The original single-file editor had working drag-and-drop and
   a file picker, so this is a **user-visible regression** on this branch until upload is
   reimplemented against the multi-file API.
3. **`window.confirm` for destructive actions** on both file delete and script delete — matches
   the brief but is inconsistent with the Radix dialogs used elsewhere in the app.
4. **Config saves via two different affordances** — explicit Save for name/description,
   instant-on-change for the entrypoint select. Defensible, but a user could reasonably expect
   Save to cover the whole tab.
5. **No run history** in the Logs tab — only the run started in the current session, same as the
   original. `currentRunId` resets on reload.
