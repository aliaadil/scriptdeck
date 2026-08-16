# User Isolation — Design

**Date:** 2026-08-16
**Status:** Approved (pending spec review)
**Branch:** `feat/sec-user-isolation`
**Threat model:** Good-citizen isolation. Block accidental cross-read; trust users not to be malicious.

## Goal

When a user runs a script through ScriptDeck, that script must not be able to read another user's source files, env ciphertext, venvs, node_modules, or logs. Every user sees a filesystem rooted at their own subtree; no other user is reachable.

## Non-Goals

- Hardening against a determined, knowledgeable attacker (out of scope; would require Landlock + seccomp + non-root container).
- Network egress isolation between users.
- Rate limiting / DoS prevention per user (separate feature).
- Resource quotas (CPU, memory) per user (separate feature).
- Cross-user shared volumes / datasets.

## Constraints

- Self-hosted single-container deployment. No docker-in-docker.
- Container runs as root today and stays as root; drop all caps, add only `SYS_CHROOT` + `SYS_ADMIN`.
- Languages: Python, Node today; bash, Ruby, Go planned.
- Pet project, small user count, so we do not optimise for thousands of concurrent users.

## Storage Layout

Per-user subtree under `/storage`. Logs live inside the user's dir (simplest chroot = one tree).

```
/storage/
├── users/<user_id>/
│   ├── scripts/<script_id>/source.{py,js,sh,...}
│   ├── envs/<script_id>/.env.encrypted
│   ├── venvs/<script_id>/.venv/...
│   ├── node_modules/<script_id>/...
│   └── logs/<run_id>.log
└── locks/<script_id>.lock
```

DB: `scripts.user_id` exists in the multi-user schema. Add index `(user_id, id)`. Every API query that reads or writes a script, env, run, or log filters by `user_id = current_user_id`.

## Sandbox Runner

New module `src/scriptdeck/runner/sandbox.py` exposes a function the parent runner calls to exec a sandboxed subprocess:

```python
def run_sandboxed(
    *,
    user_id: int,
    script_id: int,
    cmd: list[str],
    env: dict[str, str],
    cwd: str,
    stdout_sink: Callable[[bytes], None],
    log_path: Path,
) -> int: ...
```

Implementation: `subprocess.Popen(... preexec_fn=_setup_sandbox(user_root, ro_paths, tmp_size))`. The `preexec_fn` runs in the child after `fork`, before `exec`:

1. `unshare(CLONE_NEWNS)` — private mount namespace.
2. `mount(None, "/", None, MS_REC | MS_PRIVATE, None)` — don't propagate to host.
3. Build bind-mount plan from `user_root` + runner's `sandbox_view()`:
   - `/bin`, `/lib`, `/usr`, `/etc` → RO bind from host. `/etc` restricted to `passwd`, `group`, `resolv.conf`, `ssl/certs`.
   - `/scripts/<sid>/`, `/venvs/<sid>/`, `/node_modules/<sid>/`, `/envs/<sid>/`, `/logs/` → bind from user subtree, RW.
4. `mount("tmpfs", "/tmp", "tmpfs", 0, "size=64M,mode=1777")` — scratch space.
5. `os.chroot(user_root)`. Parent passes `cwd = <user_root>/venvs/<sid>` (or `node_modules/<sid>`); after chroot the child sees that as `/venvs/<sid>`.
6. Child execs the interpreter (already on PATH via `/usr/bin`).

`preexec_fn` runs in child only; parent retains full host filesystem access for cleanup.

### Env Scrubbing

`env` arg of `run_sandboxed` is built from a hardcoded whitelist:

```
{ PATH, HOME, LANG, LC_ALL, TZ, TMPDIR, PYTHONDONTWRITEBYTECODE, PYTHONUNBUFFERED }
```

…plus the script's decrypted env (from `env_service.decrypt_lines`).

The parent's `os.environ` is **never** copied into the script's env. There is no need to scrub the parent; the parent simply doesn't leak.

## Runner Protocol Extension

`LanguageRunner` gains one method:

```python
class LanguageRunner(Protocol):
    name: str
    async def provision(self, work_dir: Path, deps: list[str]) -> Path: ...
    def build_command(self, interpreter: Path, source_path: Path, env: dict[str, str]) -> list[str]: ...
    def sandbox_view(self) -> SandboxView: ...   # NEW
```

`SandboxView` is a list of `(host_path, jail_path, mode)` tuples plus any runner-specific env vars. The sandbox module unions the views of all runners registered for the script's language.

Adding a new language (Ruby, Go) is a registration + `sandbox_view()` implementation; no changes to the sandbox executor.

## Container Capabilities

`docker-compose.yml`:

```yaml
cap_drop:
  - ALL
cap_add:
  - SYS_CHROOT
  - SYS_ADMIN
```

`Dockerfile` continues to run as root. We do not remap users.

## Error Handling

| Failure | Detection | Behavior |
|---|---|---|
| Mount fails in child preexec | OSError in child | Child dies before exec; parent Popen raises. Run status='error', log = `mount failed: <path>: <reason>`. |
| chroot fails | OSError EPERM | Same as above. |
| Interpreter not bound | execve returns ENOENT | Log says "interpreter not provisioned". |
| Script reads `/storage/users/<other>/...` | OSError ENOENT | Captured as Python exception, logged normally. |
| Script writes to `/usr/` | OSError EROFS | Captured. |
| Disk full on tmpfs | OSError ENOSPC | Self-limiting. |
| Env decryption fails | exception | Run errored before exec; user sees reason. |
| Parent dies mid-run | Child reparented, hangs | Acceptable; killed by container restart. |

## Migration

One-shot CLI `scriptdeck migrate-users`:
- Reads existing `/storage/scripts/<id>`, `/storage/envs/<id>`, `/storage/venvs/<id>`, `/storage/node_modules/<id>`, `/storage/logs/<id>.log`.
- Looks up each `script_id` -> `user_id` in DB.
- Moves files into `/storage/users/<user_id>/...`.
- Idempotent. `--dry-run` by default.
- Backend must be read-only during migration.

## Rollout

1. Land sandbox module + tests behind `SCRIPTDECK_SANDBOX_ENABLED=true` (default `false`).
2. Land migration CLI.
3. Operator runs migration on existing data.
4. Operator flips flag in `docker-compose.yml`.
5. One-week soak.
6. Flip default to `true`; remove flag.

## Testing

**Unit (`tests/test_sandbox.py`):**
- `bind_plan()` output for a given user_root + SandboxView.
- env-scrub function strips non-whitelisted vars.
- tmpfs size, RO flag passing.

**Integration (`tests/test_runner_isolation.py`):**
- Real subprocesses, two users, two scripts.
- Alice script reads `/storage/users/bob/scripts/X/source.py` -> OSError.
- Alice script writes to `/storage/users/bob/...` -> OSError.
- Alice script reads `/etc/passwd` -> succeeds (RO).
- Alice script writes to `/usr/` -> OSError EROFS.
- Bob's script runs normally, sees only its own files.
- Alice's env does not contain `SCRIPTDECK_JWT_SECRET` or `SCRIPTDECK_ENV_ENCRYPTION_KEY`.

**E2E (extend `tests/e2e/smoke`):**
- Create user A and user B via API.
- User A creates script, runs it.
- User B lists scripts -> empty.
- User B tries to GET script A's source -> 403/404.
- User B's script tries to read A's path -> run log captures OSError.

## Documentation

- `README.md` storage-layout diagram updated.
- New "Security model" section: what is isolated, what is not, what users must not rely on.
- `ROADMAP.md` v2.1 entry: per-user sandbox + migration.

## Open Questions

None — design fully resolved through brainstorming on 2026-08-16.
