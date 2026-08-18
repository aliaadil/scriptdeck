# Script Editor Multi-file + Quick-start — Design

**Date:** 2026-08-17
**Branch:** `feat/script-editor`
**Status:** Approved (sections 1-3)

## Purpose

Take the current single-file Monaco editor for Kindling scripts to the next level: quick-start cards for new scripts, file tree sidebar for multi-file editing, and per-file save with debounce. Existing single-file flow keeps working (one file = `main.py`/`main.js` in the script directory).

## Decisions (from brainstorming)

- **New script UX:** Quick-start cards. Python / Node / Bash. Picking a card seeds `main.<ext>` + empty `.env` and navigates to the editor.
- **Multi-file UX:** Tree sidebar always visible. No mode toggle.
- **Backend model:** Filesystem-backed. `scripts.source_path` is the directory; new `entrypoint` column picks the runnable file.
- **`.env` files:** Plain text in tree. Existing EnvProvider (envs.py) stays as the dedicated env-var editor — separate surface.
- **Entrypoint:** Config tab `Entrypoint` field. Defaults to `main.<ext>`.

## Frontend

### Routes

- `/scripts/new` — Quick-start cards. No tree, no editor.
- `/scripts/:id` — Tree sidebar + Monaco editor + Config tab.

### New script page

Three cards: Python (🐍), Node.js (🟢), Bash (➜). Each shows what gets seeded (`main.py` + `.env` etc.). Bottom: `◯ Blank editor (advanced)` link.

Picking a card:
1. `POST /scripts` with `{ name, language, template: language, source: "" }`.
2. Backend seeds `main.<ext>` + empty `.env`. Sets `entrypoint`.
3. Navigate to `/scripts/:id`.

### Editor page layout

```
┌──────────────────────────────────────────────────────────────┐
│  <name>                                      [Run] [Save]    │
├──────────────┬───────────────────────────────────┬───────────┤
│  Files       │  <active file>                    │  Config   │
│  ────────    │  ─────────────────────            │  ───────  │
│  ▸ main.py ● │  (Monaco editor)                  │  Name     │
│  ▸ .env      │                                   │  Lang     │
│  ▸ utils.py  │                                   │  Entrypnt │
│              │                                   │  Desc     │
│  [+ Add]     │                                   │           │
│  [↑ Upload]  │                                   │           │
└──────────────┴───────────────────────────────────┴───────────┘
```

Behaviour:
- Tree shows files under `scripts/<id>/` recursively. Subdirs as collapsible groups.
- Active file marked with dot. Dot turns amber on unsaved changes, green when saved.
- `+ Add file` opens dialog: name (path under script dir), optional initial content. Rejects name with `..` or leading `/`.
- `↑ Upload` mirrors today's drop-one-file flow but adds to tree instead of replacing.
- File context menu (right-click): Rename, Delete, Download. Delete refuses on entrypoint file.
- `Save` button: bulk save dirty files (parallel `PUT`). Per-file save debounced 1.5s on edit.

### Tabs

- `Editor` (default) — tree + Monaco.
- `Config` — name, language (locked after first save), entrypoint dropdown (lists `*.py` / `*.js` / `*.sh`), description.
- `Logs` — unchanged from today.

### Components

- `frontend/src/pages/ScriptNew.tsx` — quick-start cards.
- `frontend/src/components/editor/FileTree.tsx` — sidebar.
- `frontend/src/components/editor/FileTabs.tsx` — active-file header.
- `frontend/src/components/editor/FileDialog.tsx` — add/rename dialog.
- `frontend/src/components/editor/EditorPanel.tsx` — Monaco + per-file debounce.
- `frontend/src/components/editor/QuickStartCards.tsx` — card row.
- `frontend/src/api/scripts.ts` — typed API client.

## Backend

### Schema change

- `scripts.entrypoint` (str, NOT NULL, default `'main.py'` for python, `'main.js'` for node, `'main.sh'` for bash). Set by backend on `POST /scripts` based on language.
- Migration backfills existing rows with the basename of `source_path`.

### Storage

Each script: `storage/scripts/<id>/`. Files stored as raw text. Already true for existing rows.

### Endpoints

| Method | Path | Purpose | Body |
|---|---|---|---|
| `POST` | `/scripts` | Create script. New `template` field seeds files. | `{ name, language, template?, source?, description? }` |
| `GET` | `/scripts/{id}` | Existing. Returns `entrypoint` plus existing fields. | — |
| `PUT` | `/scripts/{id}` | Now accepts `entrypoint`. | `{ name?, description?, entrypoint? }` |
| `GET` | `/scripts/{id}/files` | List files. | — |
| `GET` | `/scripts/{id}/files/{path}` | Read one file. | — |
| `PUT` | `/scripts/{id}/files/{path}` | Write one file. | `{ content }` |
| `DELETE` | `/scripts/{id}/files/{path}` | Delete file. 409 if entrypoint. | — |
| `POST` | `/scripts/{id}/files` | Create new file. | `{ path, content }` |
| `GET` | `/scripts/{id}/source` | Read entrypoint content (legacy). | — |
| `POST` | `/scripts/{id}/run` | Run entrypoint. 422 if entrypoint file missing. | — |

### Validation

- Path: regex `^[a-zA-Z0-9._-]+(/[a-zA-Z0-9._-]+)*$`. Rejects `..`, leading `/`, NUL.
- File size: ≤ 1 MB per file (configurable later).
- Files per script: ≤ 50.
- Entrypoint path must exist in tree or Run returns 422.

### Seed templates

| Language | Files seeded |
|---|---|
| python | `main.py` (imports `os`, prints a hello, reads `API_KEY` from env), `.env` (empty) |
| node | `main.js` (reads `API_KEY`, prints), `.env` (empty) |
| bash | `main.sh` (prints hello, `set -euo pipefail`), `.env` (empty) |

`source` field in `POST /scripts` still accepted for backward compat — when supplied, written to `main.<ext>` (overriding template seed).

### Runner

`runner/executor.py`: `cwd = storage / source_path`, `cmd = [interpreter, entrypoint]`. Already mostly this shape. No semantic change for users with one file.

## Data flow

**Save (per file):**
1. User edits in Monaco → local state.
2. Debounce 1.5s.
3. `PUT /scripts/{id}/files/{path}` with content.
4. Backend writes to disk, returns `{ path, size, updated_at }`.
5. Frontend updates tree row, dot turns green.

**Save (manual):**
1. Click `Save` → parallel `PUT` for each dirty file.
2. Toast on success/failure.

**Run:**
1. `POST /scripts/{id}/run`.
2. Backend resolves entrypoint. 422 if missing.
3. Spawn runner with `cwd` = source dir, argv = `[interpreter, entrypoint]`.
4. Logs stream as today.

## Error handling

| Case | Frontend | Backend |
|---|---|---|
| Path traversal | Toast + red border on file input | 400 |
| Disk full | Toast "Server out of space" | 507 |
| File size > 1 MB | Toast + block save | 413 |
| File count > 50 | Toast + block add | 422 |
| Entrypoint deleted before run | Banner: "Entrypoint missing — pick another" | 422 |
| Server-side mtime drift | Toast "File changed on server — refresh?" + reload button | 409 |
| 5xx on save | Retry once after 1s. Toast on second failure. | n/a |
| Backend offline | Same as 5xx | n/a |

## Testing

### Frontend (Vitest + RTL)

- `FileTree` renders, expands subdirs, marks active file.
- `EditorPanel` debounce calls `PUT` after 1.5s idle.
- `FileDialog` rejects `..` and leading `/`.
- `ScriptNew` cards issue correct `POST` and navigate.
- `Config` dropdown updates entrypoint and re-runs use new path.

### Backend (pytest)

- File CRUD endpoints round-trip.
- Path traversal rejected (`../etc/passwd`, `/etc/passwd`, `foo\0bar`).
- File size + count limits enforced.
- Entrypoint delete refused.
- Migration backfills `entrypoint` from existing `source_path`.
- Run returns 422 when entrypoint file missing.

### E2E (Playwright)

- New script → Python card → main.py + .env in tree → edit main.py → save → run → success.
- New script → Bash card → run → success.
- Add file → save → reload page → file persists.
- Delete entrypoint → Run fails with banner.

## Non-goals

- Folder creation/deletion UI (subdirs auto-created on file add).
- Git integration.
- File diff/merge.
- Sharing link to file.
- Drag-to-reorder in tree.

## Open follow-ups (post-merge)

- Highlight active file in URL (`?file=main.py`) for deep linking.
- Syntax-aware word wrap per file type.
- File search (cmd+p style).
- Show file size in tree.
- "Open in editor" link for IDE integration.

## Approval

Sections 1 (Frontend), 2 (Backend), 3 (Data flow + errors + testing) approved by user 2026-08-17.
