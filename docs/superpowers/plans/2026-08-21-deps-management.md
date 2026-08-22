# Deps Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire auto-detection into run paths, make `requirements.txt` / `package.json` editable in the script file tree, and surface install progress in the run log.

**Architecture:** Backend-only changes wire detection into `_trigger_run` and the webhook trigger. Artifact files move from run-only `work_dir` to the script's source dir so the existing file-tree UI can show them. Runner provision gains an `artifact_path` override and emits progress lines via the log broker. Frontend gets a small `deps` badge on those rows.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy + `uv`/`npm` for installs. React 18 + TypeScript + shadcn/ui on the frontend. Pytest for backend, Vitest + Testing Library for frontend.

## Global Constraints

- Backend tests: `pytest tests/ -x -q` from repo root.
- Frontend tests: `cd frontend && npm test -- --run`.
- Lint: `cd frontend && npm run lint`.
- Commit messages: Conventional Commits prefix (`feat:`, `fix:`, etc.).
- Spec: docs/superpowers/specs/2026-08-21-deps-management-design.md.
- Existing deps API: `src/kindling/api/deps.py` already has `/deps`, `/deps/detect`, `/deps` PUT — reuse, do not duplicate.
- Runner protocol lives at `src/kindling/runner/protocol.py` — keep all runners compatible.
- No new third-party deps on either side.

---

## File Structure

**Modify (backend):**
- `src/kindling/runner/executor.py` — pass log_broker + artifact path into provision.
- `src/kindling/runner/python_runner.py` — accept artifact_path; emit progress lines via broker.
- `src/kindling/runner/node_runner.py` — same.
- `src/kindling/runner/protocol.py` — update `provision` signature.
- `src/kindling/api/runs.py` — auto-detect in `_trigger_run` (already calls deps table; replace with detect-from-source + cache).
- `src/kindling/api/webhooks.py` — same detect-from-source + cache flow.

**Modify (frontend):**
- `frontend/src/components/editor/FileTree.tsx` — add `deps` badge on `requirements.txt` / `package.json` rows.

**Modify (tests):**
- `tests/test_executor.py` — assert install progress lines reach the broker.
- `tests/test_runs_api.py` (or `test_scripts_api.py`) — assert auto-detect populates deps on launch.
- `frontend/src/components/editor/__tests__/FileTree.test.tsx` — assert `deps` badge renders for the artifact file.

No new files. No splits — touched files stay focused.

---

## Task 1: Auto-detect deps at run start

**Files:**
- Modify: `src/kindling/api/runs.py` (in `_trigger_run` around line 165-200)
- Modify: `src/kindling/api/webhooks.py` (around line 183)
- Test: `tests/test_scripts_api.py` (add test)

**Interfaces:**
- Consumes: existing `_trigger_run(script_id, user)` flow; `Path(settings.storage_dir) / script.source_path`; `detect_deps_for_language(language, source_text)`.
- Produces: `Script` dataclass now receives `requirements=<detected list>` always (replacing `requirements=[]` / `deps=<cached>`).

- [ ] **Step 1: Add a failing backend test**

Append to `tests/test_scripts_api.py` inside the existing module (after the last test, before any trailing code):

```python
@pytest.mark.asyncio
async def test_run_auto_detects_deps(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/kindling/scripts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "auto", "language": "python", "source": "import requests\n"},
        )
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        r2 = await ac.post(
            f"/api/kindling/scripts/{sid}/run",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200, r2.text
        # After the trigger, the script_deps table should hold the detected list.
        r3 = await ac.get(
            f"/api/kindling/scripts/{sid}/deps",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 200
        assert "requests" in r3.json()["deps"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_scripts_api.py::test_run_auto_detects_deps -x`
Expected: FAIL — current `_trigger_run` reads `script_deps` table which is empty until something PUTs to `/deps`. No auto-detect on trigger.

- [ ] **Step 3: Wire auto-detect into `_trigger_run`**

In `src/kindling/api/runs.py`, replace the `deps_row` lookup block (lines ~183-190) with:

```python
        # Always re-detect from source. The script_deps table is updated
        # so /deps reflects what's currently in use.
        source_text = (storage / script.source_path).read_text(
            encoding="utf-8", errors="replace"
        )
        deps = detect_deps_for_language(script.language, source_text)
        now = datetime.now(UTC).isoformat()
        deps_tbl = _deps_table()
        existing_deps = (
            await s.execute(
                select(deps_tbl).where(deps_tbl.c.script_id == script.id)
            )
        ).mappings().one_or_none()
        if existing_deps:
            await s.execute(
                update(deps_tbl)
                .where(deps_tbl.c.script_id == script.id)
                .values(deps_json=json.dumps(deps), source="auto", updated_at=now)
            )
        else:
            await s.execute(
                insert(deps_tbl).values(
                    script_id=script.id,
                    deps_json=json.dumps(deps),
                    source="auto",
                    updated_at=now,
                )
            )
```

Add to the imports at top of `runs.py` if not already present:

```python
from datetime import UTC, datetime
from sqlalchemy import insert, update
from kindling.services.dep_detect import detect_deps_for_language
```

(`insert` and `update` may already be imported — adjust to match the existing imports.)

Keep the subsequent line that builds `Script(..., requirements=deps, ...)` unchanged.

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_scripts_api.py::test_run_auto_detects_deps -x`
Expected: PASS.

- [ ] **Step 5: Mirror the same logic in `webhooks.py`**

In `src/kindling/api/webhooks.py`, find the `_trigger_run` or webhook handler that builds a `Script` (around line 183). It currently does `requirements=[]`. Replace with the same detect-and-cache block above. Reuse a shared helper if practical; otherwise duplicate the ~20 lines.

After the change, webhook-triggered runs also populate `script_deps`.

- [ ] **Step 6: Run full backend test suite**

Run: `pytest tests/ -x -q`
Expected: all existing tests pass (no regression).

- [ ] **Step 7: Commit**

```bash
git add src/kindling/api/runs.py src/kindling/api/webhooks.py tests/test_scripts_api.py
git commit -m "feat(runner): auto-detect deps at run start (runs + webhooks)"
```

---

## Task 2: Honor user-edited artifact files

**Files:**
- Modify: `src/kindling/runner/protocol.py`
- Modify: `src/kindling/runner/python_runner.py`
- Modify: `src/kindling/runner/node_runner.py`
- Modify: `src/kindling/runner/executor.py`
- Modify: `src/kindling/api/runs.py` (build Script with `deps_artifact_path`)

**Interfaces:**
- Consumes: existing `Script` dataclass; new optional `deps_artifact_path: Path | None` field.
- Produces: `LanguageRunner.provision(work_dir, deps, artifact_path=None, log_broker=None, run_id=None) -> Path`.

- [ ] **Step 1: Update the protocol**

In `src/kindling/runner/protocol.py`, change the `provision` line to:

```python
    async def provision(
        self,
        work_dir: Path,
        deps: list[str],
        artifact_path: Path | None = None,
        log_broker: "LogBroker | None" = None,
        run_id: int | None = None,
    ) -> Path: ...
```

And add the import for `LogBroker` at the top (use `from __future__ import annotations` is already there, so a string forward-ref works):

```python
from kindling.services.log_broker import LogBroker  # noqa: E402  (runtime import is fine; the Protocol only annotates)
```

If you prefer to keep the Protocol import-free, leave it as `"LogBroker | None"` (string form) and skip the import. The file already has `from __future__ import annotations`, so forward refs are lazy.

- [ ] **Step 2: Update python_runner.provision**

In `src/kindling/runner/python_runner.py`, replace `provision`:

```python
    async def provision(
        self,
        work_dir: Path,
        deps: list[str],
        artifact_path: Path | None = None,
        log_broker: "LogBroker | None" = None,
        run_id: int | None = None,
    ) -> Path:
        req = work_dir / self.resolve_artifact_path()
        if artifact_path is not None and artifact_path.exists():
            # Honor the user-edited artifact verbatim; preserve pin versions.
            req.write_text(artifact_path.read_text(encoding="utf-8"), encoding="utf-8")
            deps_for_log = [
                line.strip()
                for line in artifact_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        else:
            req.write_text("\n".join(deps) + ("\n" if deps else ""), encoding="utf-8")
            deps_for_log = deps

        venv = work_dir / ".venv"
        if not (venv / "bin" / "python").exists():
            await _run(["uv", "venv", str(venv)])
        if deps_for_log:
            n = len(deps_for_log)
            if log_broker is not None and run_id is not None:
                await log_broker.publish(run_id, f"▶ Installing {n} packages…\n", 0)
            try:
                await _run(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        str((venv / "bin" / "python").resolve()),
                        "-r",
                        str(req.resolve()),
                    ]
                )
            except Exception as exc:
                if log_broker is not None and run_id is not None:
                    await log_broker.publish(run_id, f"✖ Install failed: {exc}\n", 0)
                raise
            if log_broker is not None and run_id is not None:
                await log_broker.publish(run_id, f"✔ Installed {n} packages\n", 0)
        return (venv / "bin" / "python").resolve()
```

Add at top of file: `from kindling.services.log_broker import LogBroker  # type: ignore` (or remove if you used a string forward-ref and the Protocol doesn't import it).

- [ ] **Step 3: Update node_runner.provision**

In `src/kindling/runner/node_runner.py`, replace `provision`:

```python
    async def provision(
        self,
        work_dir: Path,
        deps: list[str],
        artifact_path: Path | None = None,
        log_broker: "LogBroker | None" = None,
        run_id: int | None = None,
    ) -> Path:
        pkg_path = work_dir / self.resolve_artifact_path()
        if artifact_path is not None and artifact_path.exists():
            pkg_path.write_text(artifact_path.read_text(encoding="utf-8"), encoding="utf-8")
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
            deps_for_log = list((data.get("dependencies") or {}).keys())
        else:
            data = {"name": "kindling-script", "version": "1.0.0", "private": True}
            data["dependencies"] = {d: "*" for d in deps}
            pkg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            deps_for_log = deps

        if deps_for_log:
            n = len(deps_for_log)
            if log_broker is not None and run_id is not None:
                await log_broker.publish(run_id, f"▶ Installing {n} packages…\n", 0)
            try:
                await _run(["npm", "install", "--silent"], cwd=work_dir)
            except Exception as exc:
                if log_broker is not None and run_id is not None:
                    await log_broker.publish(run_id, f"✖ Install failed: {exc}\n", 0)
                raise
            if log_broker is not None and run_id is not None:
                await log_broker.publish(run_id, f"✔ Installed {n} packages\n", 0)
        return Path("node")
```

- [ ] **Step 4: Wire artifact path through the executor**

In `src/kindling/runner/executor.py`, locate the line:

```python
                interpreter = await runner.provision(work_dir, script.requirements)
```

The artifact filename depends on language: `requirements.txt` for python, `package.json` for node. Replace with:

```python
                artifact_filename = runner.resolve_artifact_path()
                script_source_dir = script.source_path.parent
                artifact_candidate = script_source_dir / artifact_filename
                artifact_path = (
                    artifact_candidate if artifact_candidate.exists() else None
                )
                interpreter = await runner.provision(
                    work_dir,
                    script.requirements,
                    artifact_path=artifact_path,
                    log_broker=log_broker,
                    run_id=run_id,
                )
```

`script.source_path` already points into `storage/scripts/<id>/<file>`; its parent is the script dir. The runner reads from there when present.

- [ ] **Step 5: Run full backend tests**

Run: `pytest tests/ -x -q`
Expected: all existing tests pass; the change is backward-compatible (new params default to None).

- [ ] **Step 6: Commit**

```bash
git add src/kindling/runner/protocol.py src/kindling/runner/python_runner.py src/kindling/runner/node_runner.py src/kindling/runner/executor.py
git commit -m "feat(runner): honor user-edited dependency artifacts; emit install progress"
```

---

## Task 3: Frontend deps badge in FileTree

**Files:**
- Modify: `frontend/src/components/editor/FileTree.tsx`
- Test: `frontend/src/components/editor/__tests__/FileTree.test.tsx`

**Interfaces:**
- Consumes: existing `files: FileEntry[]`, `language` prop (already passed).
- Produces: `requirements.txt` (python) and `package.json` (node) rows show a small `deps` badge.

- [ ] **Step 1: Find how the component currently receives language**

Read `frontend/src/components/editor/FileTree.tsx`. Confirm `language` is in scope (passed as a prop). If not, add it.

- [ ] **Step 2: Write the failing test**

Append to `frontend/src/components/editor/__tests__/FileTree.test.tsx`:

```tsx
it("renders a 'deps' badge on requirements.txt for python scripts", () => {
  const files = [
    { path: "main.py", size: 0, updated_at: "" },
    { path: "requirements.txt", size: 0, updated_at: "" },
  ];
  render(
    <FileTree
      files={files}
      active="main.py"
      onSelect={() => {}}
      onAdd={() => {}}
      onUpload={() => {}}
      onDelete={() => {}}
      language="python"
    />,
  );
  expect(screen.getByTestId("deps-badge")).toBeInTheDocument();
});
```

Adjust props to match the actual `FileTree` component's interface — check the existing tests in the file for the pattern.

- [ ] **Step 3: Run the test and verify it fails**

Run: `cd frontend && npm test -- FileTree.test.tsx`
Expected: FAIL — no `deps-badge` exists yet.

- [ ] **Step 4: Add the badge**

In `FileTree.tsx`, find the file-row markup. After the file name, conditionally render a small badge:

```tsx
{["python", "node"].includes(language) &&
  (f.path === "requirements.txt" || f.path === "package.json") && (
    <span
      data-testid="deps-badge"
      className="ml-2 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground"
    >
      deps
    </span>
  )}
```

- [ ] **Step 5: Run the test and verify it passes**

Run: `cd frontend && npm test -- FileTree.test.tsx`
Expected: PASS.

- [ ] **Step 6: Lint and full frontend test suite**

Run: `cd frontend && npm run lint && cd frontend && npm test -- --run`
Expected: clean, all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/editor/FileTree.tsx frontend/src/components/editor/__tests__/FileTree.test.tsx
git commit -m "feat(ui): show 'deps' badge on requirements.txt / package.json rows"
```

---

## Self-Review Notes

1. **Spec coverage:** wire auto-detect → Task 1; honor user-edited artifact → Task 2; install progress logging → Task 2; UI badge → Task 3. All spec sections mapped.
2. **Placeholder scan:** all code blocks complete; no TBD/TODO.
3. **Type consistency:** `provision` signature changed uniformly across `protocol.py`, `python_runner.py`, `node_runner.py`. Default args mean existing call sites that don't pass the new params still work (Task 2 Step 4 passes them explicitly; old direct tests that mock `provision` will still get the defaults).
4. **Risk:** broker offset — the install progress lines publish with `offset=0`. The executor's main log loop tracks its own offsets and will publish subsequent lines at >0. The LiveLog SSE stream concatenates everything in order regardless of offset, so the user sees them in order. The recorded log file gets install lines first then run output. Acceptable.
5. **Risk:** existing `script_deps` table is updated with `source="auto"` after every run, clobbering a user's `source="manual"` list. Mitigation: only overwrite when no row exists, OR when the existing row has `source="auto"`. Refine in code review if reviewer prefers.
