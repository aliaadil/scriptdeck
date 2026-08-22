# Dependency Management — Design

Date: 2026-08-21
Status: Draft
Branch: `kindling/triggers`

## Context

PR #19 added per-script triggers (multi-schedule + webhook). While using it,
two rough edges showed up:

1. The runner auto-detection in `python_runner.detect_deps` /
   `node_runner.detect_deps` is never wired into the trigger / run paths.
   `runs.py` and `webhooks.py` hardcode `requirements=[]`, so a script
   that imports a third-party module (e.g. `requests`, `dotenv`) crashes
   with `ModuleNotFoundError` on launch.
2. There is no UI to manage dependencies. The user can't install
   packages, see what was detected, or pin versions. The only way to
   use `python-dotenv` (or any third-party import) today is to fail,
   notice the error, and have no path forward.

This spec wires auto-detection into the run path, makes the dependency
artifact editable in the file tree, and surfaces install progress in
the run log.

## Goals

- A script that `import`s a third-party module runs without manual
  setup.
- If the install fails, the user sees a clear error and can retry
  after editing source.
- The user can pin versions by editing `requirements.txt` /
  `package.json` in the file tree.
- The user can see install progress in the run log.

## Non-Goals

- Lock files, PEP 621 metadata, node `package-lock.json` review UI.
- Dependency conflict resolution across scripts.
- Re-installing on every source save (only on run).
- Bash scripts — no dependency artifact.
- Changing how `.env` secrets are loaded (already decrypted into
  subprocess env in `executor.py:79-88`).

## Design

### 1. Wire auto-detection

Files: `src/kindling/api/runs.py:200`, `src/kindling/api/webhooks.py:183`

Replace `requirements=[]` with:

```python
source_path = (storage / script.source_path).resolve()
source_text = source_path.read_text(encoding="utf-8", errors="replace")
deps = detect_deps_for_language(script.language, source_text)
```

Then pass `requirements=deps` to the `Script` dataclass. Both paths
share the same logic — extract into a small helper in
`src/kindling/services/script_service.py` if duplication grows.

### 2. Honor user-edited artifact files

Files:
- `src/kindling/runner/python_runner.py`
- `src/kindling/runner/node_runner.py`
- `src/kindling/runner/executor.py` (decide where the artifact lives)
- `src/kindling/services/script_files.py` (artifact write semantics)

Behavior:

- The artifact file (`requirements.txt` for python, `package.json`
  for node) lives in the **script's source directory**
  (`storage/scripts/<id>/`), NOT in the run-only `work_dir`.
- `Script` dataclass gains a `deps_artifact_path: Path | None` field.
  Set when the artifact exists in the source dir.
- `runner.provision(work_dir, deps)` becomes
  `runner.provision(work_dir, deps, artifact_path=None)`:
  - If `artifact_path` is provided, copy it into `work_dir` verbatim
    and `uv pip install -r` / `npm install` from it (don't overwrite).
  - Otherwise generate from `deps` as today.
- This makes user-pinned versions stick across runs.

### 3. Editable artifact in the file tree

Files:
- `src/kindling/api/scripts.py` — list/get/put/delete endpoints already
  cover any path; just need to make sure `requirements.txt` and
  `package.json` are listed in `GET /scripts/{id}/files` (they will be,
  since they're just files in the source dir after step 2).
- `frontend/src/components/editor/FileTree.tsx` — add a small `deps`
  badge on rows whose path matches the deps filename for the script's
  language.

Behavior:

- Artifact file is editable like any other file (PUT updates it; that
  version is honored at the next run).
- DELETE removes it → runner falls back to auto-generation from
  source detection.
- CREATE: a new empty artifact is created on demand.

### 4. Install progress in the run log

Files:
- `src/kindling/runner/python_runner.py`
- `src/kindling/runner/node_runner.py`
- `src/kindling/runner/executor.py` (or pass `LogBroker` to provision)

Add `log_broker: LogBroker | None = None` parameter to
`runner.provision`. Inside `provision`, before `uv pip install` /
`npm install`, emit one log line:

```
▶ Installing <N> packages…
```

Capture stdout/stderr from the install command and forward through the
broker. After the install succeeds, emit:

```
✔ Installed <N> packages in <Xs>
```

On failure, the existing stderr capture (today swallowed inside
`_run`) should be passed through to the broker as well so the user
sees the actual install error. On failure the run fails and the
existing exception path surfaces it.

In `executor.py`, pass `log_broker` from the run context into
`runner.provision`.

### 5. UI affordance

No new tab. The artifact file is opened in the existing Editor pane.
A small `deps` badge on the row in the file tree tells the user this
file is auto-managed but editable.

## Files Touched

Backend:

- `src/kindling/api/runs.py`
- `src/kindling/api/webhooks.py`
- `src/kindling/runner/executor.py`
- `src/kindling/runner/python_runner.py`
- `src/kindling/runner/node_runner.py`
- `src/kindling/services/script_service.py` (helper if needed)
- `src/kindling/services/script_files.py`

Frontend:

- `frontend/src/components/editor/FileTree.tsx`

Tests:

- `src/kindling/tests/test_dep_detect.py` — already exists; add cases
  for user-edited artifact taking precedence.
- `src/kindling/api/tests/test_runs.py` — assert deps detected at run.
- `frontend/src/components/editor/__tests__/FileTree.test.tsx` — badge.

## Risks

- First-run install latency. Mitigation: install only when artifact is
  absent OR detected deps changed. Acceptable for now.
- User-edited `requirements.txt` may pin incompatible versions — the
  error surfaces in the log, user can fix.
- Sandboxed runs (`sandbox_enabled=True`) currently re-mount the
  script dir; needs the artifact file to be reachable from inside the
  jail. Verify the existing bind mount covers `storage/scripts/<id>/`
  for both sandbox and legacy paths. If not, add the bind.
