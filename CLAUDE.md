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
- `interface/` — entrypoints: `shell.py` (interactive CLI) and **`rpc.py`**
  (HTTP control server, below).
- `app/` — sample workloads to snapshot (NOT the control plane).
- `tests/` — pytest (`test_rpc.py`); root `conftest.py` puts the repo root on
  `sys.path` (the project is run from its root, not installed).

## RPC interface — `interface/rpc.py`
A FastAPI control server that exposes the `controller` managers over HTTP. This
is what the [harbor](https://github.com/harbor-framework/harbor) `checkpoint-lite`
environment talks to (it was the "RPC interface: to be implemented" in
`interface/README.md`). Run from the repo root (where the `checkpoint-lite`
binary/symlink lives):

```bash
(sudo) python3 -m interface.rpc --host 0.0.0.0 --port 8088
```

Single worker (in-memory session registry). Endpoints: `GET /health`;
`POST /sessions`; `POST /sessions/{id}/{snapshot,restore,fork,exec,upload,download}`;
`GET /sessions/{id}/{snapshots,tree}`; `DELETE /sessions/{id}`. File transfer is
exec-based (base64; `tar` for dirs). See `interface/README.md` for details.

## harbor integration
harbor's `CheckpointLiteEnvironment` (out-of-tree, loaded via `import_path`)
drives StateFork two ways — **both go through `controller.create_env_manager`**:
- `transport="rpc"` → HTTP to `interface/rpc.py`.
- `transport="local"` → `import controller` in-process (requires StateFork's
  deps importable + the `checkpoint-lite` binary resolvable from cwd).

The integration is meant to keep StateFork's existing code unmodified — the RPC
server, tests, and `conftest.py` are additive.

## Requirements
Checkpoint-lite / `waypoint` (github.com/Alex-XJK/waypoint, the repo cloned as
`checkpoint-lite`) needs **Linux + CRIU + root**, and the binary must be
resolvable as `./checkpoint-lite` from the cwd (symlink it in). Firecracker
needs `paramiko` (not in `requirements.txt`). See `README.md` for per-backend
setup. Python 3.10+.

## Testing
```bash
python -m pytest tests/test_rpc.py -q
```
CRIU / the Checkpoint-lite binary can't run without a Linux+CRIU host; the tests
drive the RPC route functions with `create_env_manager` faked.

## Maintenance (do this every time)
On any change to the checkpoint-lite integration, update `INTEGRATION_REPORT.md`
in this repo **and** its counterpart in the harbor repo — keep both reports in
sync.

