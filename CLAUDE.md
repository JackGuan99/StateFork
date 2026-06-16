# CLAUDE.md — StateFork

StateFork is a lightweight, versioned snapshotting + benchmarking tool. It wraps
several checkpoint/restore backends — Docker/Podman, CRIU, Hybrid (Podman+CRIU),
**Checkpoint-lite** (a.k.a. `waypoint`), gVisor, Firecracker — behind one
`EnvironmentManager` interface.

## Layout
- `controller/` — core. `EnvironmentManager` base + per-backend managers
  (`*_env_manager.py`) + the `create_env_manager(method, **kwargs)` factory in
  `controller/__init__.py`. Managers expose `snapshot()`, `restore(id)`,
  `create_env_from_snapshot(id)`, `exec_command(cmd, timeout)`, `cleanup()`,
  plus a snapshot graph and benchmarking (`.stats`).
- `decider/` — snapshot decision strategies (physical vs. virtual snapshots).
- `interface/` — entrypoints: `shell.py` (interactive CLI), **`cli.py`**
  (one-shot Checkpoint-lite CLI — harbor's integration path, below), and
  `rpc.py` (optional HTTP control server, below).
- `app/` — sample workloads to snapshot (NOT the control plane).
- `tests/` — pytest (`test_cli.py`, `test_rpc.py`); root `conftest.py` puts the
  repo root on `sys.path` (the project is run from its root, not installed).

## Checkpoint-lite one-shot CLI — `interface/cli.py` (harbor's path)
A small, scriptable command-line front-end to the `checkpoint-lite` / `waypoint`
binary, meant to be driven **per-operation via `subprocess`** — the way
[harbor](https://github.com/harbor-framework/harbor)'s `checkpoint-lite`
environment uses it, exactly as `docker.py` shells out to `docker compose`. Run
from the repo root (where the `checkpoint-lite` binary/symlink lives):

```bash
(sudo) python3 -m interface.cli create  /path/to/context [--build|--no-build]
(sudo) python3 -m interface.cli exec     <session> "echo hi"
(sudo) python3 -m interface.cli snapshot <session>            # prints a checkpoint id
(sudo) python3 -m interface.cli restore  <session> <checkpoint-id>
(sudo) python3 -m interface.cli cleanup  <session> [--force]
```

It maps 1:1 onto the binary (`init`/`build`, `exec`, `create`, `restore`,
`cleanup`) and issues `./checkpoint-lite` **directly** — it does *not* import the
`controller` managers. That is deliberate: waypoint is already stateless per call
(session state persists on disk under `/tmp/waypoint-sessions/<sid>/`), whereas a
manager is stateful (in-memory snapshot graph) and would lose that state between
one-shot invocations; going direct also avoids `controller/__init__.py`'s eager
firecracker→paramiko import. `snapshot` passes the `-2` PID sentinel
(`PID_NOT_PROVIDED`), so waypoint checkpoints the managed shell session if the
session has one. Override the binary path with `$CHECKPOINT_LITE_BIN`.

## harbor integration
harbor's `CheckpointLiteEnvironment` (out-of-tree, loaded via `import_path`)
drives StateFork through a **single transport**: it `subprocess`es
`python -m interface.cli ...` with `cwd` set to this repo root. There is no
long-running server and no in-process import — the most Docker-consistent shape
(harbor → CLI → backend binary). File transfer is done by harbor writing/reading
the session's OverlayFS `work_dir` directly (co-located, like `docker cp`).

The integration keeps StateFork's existing code unmodified — `interface/cli.py`,
`interface/rpc.py`, the tests, and `conftest.py` are all additive.

## RPC interface — `interface/rpc.py` (optional, not on harbor's path)
A FastAPI control server that exposes the `controller` managers over HTTP
(`python -m interface.rpc --host 0.0.0.0 --port 8088`). It was the earlier harbor
transport and remains available as a standalone remote/decoupled control plane,
but the current harbor integration uses the CLI above, not this. Endpoints:
`GET /health`; `POST /sessions`;
`POST /sessions/{id}/{snapshot,restore,fork,exec,upload,download}`;
`GET /sessions/{id}/{snapshots,tree}`; `DELETE /sessions/{id}`. See
`interface/README.md`.

## Requirements
Checkpoint-lite / `waypoint` (github.com/Alex-XJK/waypoint, the repo cloned as
`checkpoint-lite`) needs **Linux + CRIU + root**, and the binary must be
resolvable as `./checkpoint-lite` from the cwd (symlink it in). Firecracker
needs `paramiko` (not in `requirements.txt`). See `README.md` for per-backend
setup. Python 3.10+.

## Testing
```bash
python -m pytest tests/test_cli.py tests/test_rpc.py -q
```
CRIU / the Checkpoint-lite binary can't run without a Linux+CRIU host; the tests
mock the seam — `test_cli.py` mocks `subprocess.run` and asserts each subcommand
issues the right binary argv; `test_rpc.py` drives the RPC route functions with
`create_env_manager` faked.

## Maintenance (do this every time)
On any change to the checkpoint-lite integration, update `INTEGRATION_REPORT.md`
in this repo **and** its counterpart in the harbor repo — keep both reports in
sync.
