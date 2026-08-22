# Manual Run Params Design

## Context

Schedules and webhooks already accept a `params_json` JSON object on the trigger and forward it to the script as `KINDLING_PARAM_<KEY>=<value>` env vars (see `src/kindling/api/webhooks.py:99` `trigger_params_env`). The ScriptEdit header's **Run** button has no equivalent — manually testing a script means re-saving it with hard-coded values, which is friction the schedules/webhook paths don't have.

User also wants the parameter shape to differ by language: Python and bash scripts typically take positional CLI arguments, Node scripts typically take `--key value` flags. The current `KINDLING_PARAM_*` env-var-only contract makes that awkward.

## Goals

- **Add a params input on manual Run** that surfaces in the ScriptEdit header, so the same `params_json` shape that schedules/webhooks use works for a one-off test click.
- **Map params to language-appropriate argv** in addition to exporting them as `KINDLING_PARAM_*` env vars, so scripts can read them however the language prefers.
- Keep the surface minimal: no per-script saved defaults, no per-run language picker.

## Non-goals

- Saving params as per-script defaults.
- Showing captured params on the Runs / Run detail page (future work).
- Per-language UI picker for env-vs-CLI shape.
- Webhook / schedule backward compatibility changes (their `params_json` shape is unchanged; only the runner learns to consume argv too).

## Decisions

| Decision | Choice |
|---|---|
| Param shape per language | Python = positional argv, Node = `--key value` flags, bash = positional argv |
| Bool values in Node | `--key` (no value) when `true`, dropped when `false` |
| Python/bash positional order | JSON key insertion order |
| UI surface | Inline expand under Run button (chevron + textarea) |
| Persistence | One-off per click; no DB defaults |
| env vars alongside argv | Always export `KINDLING_PARAM_<KEY>=<value>` regardless of language |

## Architecture

### Backend

**New module: `src/kindling/params.py`**

Pure function `argv_for(language: str, params: dict[str, Any]) -> list[str]`:

- `python`, `bash`: return `[str(v) for v in params.values()]` in dict-insertion order. Keys are ignored.
- `node`: for each `(k, v)` in dict-insertion order, append `--<k>` and then `str(v)` if the value is a string/number. Booleans: append `--<k>` when `true`, omit the key entirely when `false`.
- Raises `ValueError` for unsupported languages or non-dict input.

**Migration 017: `src/kindling/migrations/017_runs_params_json.sql`**

```sql
ALTER TABLE runs ADD COLUMN params_json TEXT;
```

Stored on the runs row so future Run-detail UI can show what params were used. Nullable: existing manual runs pre-feature have nothing.

**Runner integration**

The runner currently builds argv as `[entrypoint]` for Python/Node/bash. Append the per-language argv (when params is provided) before the entrypoint or after — pick the position that matches each runner's existing convention:

- Python: `python <entrypoint> <arg1> <arg2> …` — argv comes after the entrypoint, which is the conventional Python CLI shape (`sys.argv[1:]` are the positional args).
- Node: `node <entrypoint> --k1 v1 --k2 v2` — same, after entrypoint.
- Bash: `bash <entrypoint> <arg1> <arg2> …` — argv after entrypoint (positional).

`KINDLING_PARAM_<KEY>=<value>` env vars are exported in addition, unchanged from the trigger path.

**Endpoint: `POST /scripts/{id}/run` (`src/kindling/api/runs.py`)**

Body extends to `{ params_json?: object }`. Validated with the existing Pydantic field validator reused from `src/kindling/api/triggers.py` (a small shared validator helper, or just inline the same `field_validator("params_json")` rules). On success:

1. Resolve `argv = argv_for(script.language, params)` in the same code path that already calls `run_service.create_run`.
2. Pass `argv` into `_execute_and_finalize(run_id, script, app, param_env=…, param_argv=argv)`.
3. `create_run` writes `params_json` to the new `runs.params_json` column.
4. Store `params_json` on the response `RunOut` so the frontend can show it.

### Frontend

**`frontend/src/api/scripts.ts`**

`triggerRun(script_id, params_json?: Record<string, unknown>)` extends signature; passes body `{ params_json }` when present, omits when not.

**`frontend/src/pages/ScriptEdit.tsx`**

- Add `const [showParams, setShowParams] = useState(false)` and `const [paramsText, setParamsText] = useState("")` next to existing run state.
- Replace the single Run `Button` with a small flex group: a `ChevronDown`/`ChevronUp` icon `Button` (size icon, variant ghost) and the existing Run `Button`. Chevron toggles `showParams`.
- When `showParams`, render a one-line `<Textarea>` below the header row with placeholder `{"region":"us-east-1","shard":3}`. Parse JSON on Run click; on parse failure show a sonner error and abort the run.
- `run.mutate(undefined)` becomes `run.mutate(parsedParams)` (or `undefined` if the textarea is empty).

**No changes to**: header layout, TabsContent structure, FileTree, recent runs row, run status polling.

## Data flow

1. User clicks chevron → textarea appears with placeholder.
2. User types JSON and clicks Run.
3. Frontend parses; on success POSTs `/scripts/{id}/run` with `{params_json: parsed}`.
4. Backend validates, computes `argv`, calls `_execute_and_finalize(..., param_env={KINDLING_PARAM_*}, param_argv=argv)`.
5. Runner launches the script with argv + env.
6. `runs.params_json` recorded for later display.
7. Logs tab polls run as today; nothing else changes.

## Error handling

| Failure | UX |
|---|---|
| Frontend JSON parse error | Sonner error "Invalid params JSON"; run does not start |
| Backend Pydantic rejection | 422 with field detail (existing path) |
| Runner subprocess fails | Same as today — status flips to failure, surfaced on Logs tab |
| Empty params object | Treated as "no params"; argv is `[]`, same as today |

## Testing

**Backend unit tests** (`tests/test_params_argv.py`):

- `argv_for("python", {"region":"us","shard":3})` → `["us","3"]`.
- `argv_for("python", {})` → `[]`.
- `argv_for("node", {"region":"us","shard":3})` → `["--region","us","--shard","3"]`.
- `argv_for("node", {"verbose":true,"debug":false})` → `["--verbose"]`.
- `argv_for("bash", {"x":"y"})` → `["y"]`.
- `argv_for("ruby", {})` raises `ValueError`.

**Backend endpoint tests** (extend `tests/api/`):

- `POST /scripts/{id}/run` with `params_json={"x":"y"}` against a script that prints `sys.argv[1:]` returns a run whose log contains `['x']`-equivalent.
- Without `params_json`, argv is empty (existing behavior).

**Frontend tests** (`frontend/src/pages/__tests__/ScriptEdit.test.tsx`):

- Render ScriptEdit → click chevron → textarea appears.
- Type invalid JSON → click Run → run does not start; toast shown.
- Type valid JSON → click Run → mutationFn receives `{params_json: parsed}`.

## Files

- New: `src/kindling/params.py`, `src/kindling/migrations/017_runs_params_json.sql`, `tests/test_params_argv.py`.
- Modified: `src/kindling/api/runs.py` (endpoint body + `param_argv` plumb), `src/kindling/services/run_service.py` (insert `params_json`), `src/kindling/db/models.py` (column), `src/kindling/runner/{python,node,bash,sandbox}.py` (append argv), `frontend/src/api/scripts.ts`, `frontend/src/pages/ScriptEdit.tsx`, `frontend/src/pages/__tests__/ScriptEdit.test.tsx`.

## Open questions

None — user confirmed both `Node: --key (no value) on true` and `positional insertion order for Python/bash` in design approval.