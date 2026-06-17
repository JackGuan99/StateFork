# Checkpoint-lite Integration — StateFork change report

Cross-repo integration that exposes **StateFork's Checkpoint-lite** to the
**harbor** framework. This file is the authoritative report for **StateFork's**
side; the harbor repo has a matching `INTEGRATION_REPORT.md`.

> **Maintenance:** update this file *and* harbor's counterpart on **every**
> change to this integration. See `CLAUDE.md`.

## Design (one line)
Add a **one-shot Checkpoint-lite CLI** (`interface/cli.py`) that harbor drives
per-operation via `subprocess` (Docker-style: harbor → CLI → `waypoint` binary).
StateFork's existing code/interfaces are **unchanged**; everything here is
additive. (`interface/rpc.py`, the earlier HTTP transport, is retained but is no
longer on harbor's path.)

## Files

### New
- **`interface/cli.py`** (~140 lines) — the one-shot CLI (harbor's transport).
  - Subcommands: `create <dir> [--build|--no-build]` (prints `sid,workdir[,pid]`);
    `exec <session> <command>`; `snapshot <session> [--id]` (prints checkpoint id);
    `restore <session> <snapshot>`; `cleanup <session> [--force]`.
  - Issues `./checkpoint-lite` **directly** (does NOT import `controller`) — it
    maps 1:1 onto the binary (`init`/`build`, `exec`, `create`, `restore`,
    `cleanup`). Rationale: waypoint is stateless per call (state persists on disk
    under `/tmp/waypoint-sessions/<sid>/`), so a stateful manager (in-memory
    snapshot graph) can't be driven one-shot; going direct also avoids
    `controller/__init__.py`'s eager firecracker→paramiko import.
  - `snapshot` passes the `-2` PID sentinel (`PID_NOT_PROVIDED`) so waypoint
    checkpoints the managed shell session when one exists. `$CHECKPOINT_LITE_BIN`
    overrides the binary path (default `./checkpoint-lite`).
- **`tests/test_cli.py`** (~110 lines) — 13 tests; mocks `subprocess.run` and
  asserts each subcommand issues the right binary argv + surfaces stdout/exit code.
- **`interface/rpc.py`** (258 lines) — FastAPI control server (earlier transport;
  retained as an optional standalone remote interface, not used by harbor now).
  11 endpoints, 14 Pydantic models, `_Session`/`_Registry`, direct work_dir
  `/upload`+`/download`, `main()` (`python -m interface.rpc`).
- **`tests/test_rpc.py`** (160 lines) — 13 tests (`create_env_manager` faked).
- **`conftest.py`** (10 lines) — puts the repo root on `sys.path` for pytest.
- **`CLAUDE.md`** (agent guide).

### Modified
- **`interface/README.md`** — the RPC section "to be implemented" → full
  endpoint documentation.

### NOT changed (touched during exploration, then reverted → net zero)
`controller/__init__.py`, `controller/ckptlite_env_manager.py`. No lazy-import or
`$CHECKPOINT_LITE_BIN` changes remain — original code is intact. The CLI mirrors
the *same* `./checkpoint-lite` commands the reference manager
(`ckptlite_env_manager.py`) issues, without depending on it.

## Interfaces
- **Added:** the one-shot CLI (`interface/cli.py`, 5 subcommands) — harbor's path.
  Plus the optional HTTP RPC interface (`interface/rpc.py`, 11 endpoints) +
  `main()`, retained from the earlier design.
- **Removed / modified existing:** none.

## How to run
```bash
# harbor's path — one-shot CLI (from repo root, where ./checkpoint-lite lives):
(sudo) python3 -m interface.cli create /path/to/context --build
# optional standalone HTTP server (not used by harbor):
(sudo) python3 -m interface.rpc --host 0.0.0.0 --port 8088
```

## harbor side (counterpart)
harbor's `CheckpointLiteEnvironment` (out-of-tree, via `import_path`) drives this
through a **single transport**: it `subprocess`es `python -m interface.cli ...`
with `cwd` = this repo root, and reads/writes the session `work_dir` directly for
file transfer. No server, no in-process import. See harbor's
`INTEGRATION_REPORT.md`.

## Verification
- 26/26 tests pass (real `pytest`, WSL Ubuntu): `test_cli.py` 13 + `test_rpc.py` 13.
- Real backend — **full `build` E2E** (WSL2, `waypoint` v0.6.0 + criu + buildah,
  base image via a CN mirror): driven through the CLI, the whole chain passed —
  `create --build` (→ `sid,workdir,pid`), a compound shell `exec` (cd/export/
  var-expand + reading the Dockerfile-baked file), the `__HB_RC__` exit-code
  sentinel (`(exit 3)`→`__HB_RC__3__`), a persistent managed shell across `exec`s,
  and `snapshot`→mutate→`restore` with the file **reverting** (CRIU + OverlayFS),
  then `cleanup`. Init-session `create`/`snapshot`/`restore`/`cleanup` are also
  rc=0; waypoint runs a shell only for shell-enabled (`build`) sessions.
- harbor's real `CheckpointLiteEnvironment` class was also driven against this CLI
  end-to-end (start → exec as root and as a non-root `agent` via `runuser` →
  exit-code recovery → work_dir upload/download → snapshot/restore revert → stop).
- Full `harbor job start` agent trials over this CLI scored reward **1.0**: the
  `oracle` agent and a real **LLM agent** (host-side ReAct loop via `exec`) both
  solved a task in the checkpoint-lite container. Note: `tmux`/PTY agents (e.g.
  `terminus`) fail — the waypoint container has no `/dev/pts` (managed shell runs
  over the `bash_init` socket); use `exec`-based agents.
- **Deployment note:** the repo root must resolve **both** `./checkpoint-lite`
  (the `waypoint` binary) **and** `./bash_init` (waypoint execs
  `DefaultBashInitSrc="./bash_init"` relative to cwd for shell sessions).

## Status
Working tree (push per the user's instruction). The CLI supersedes the RPC server
as harbor's transport; the RPC server is retained additively.
