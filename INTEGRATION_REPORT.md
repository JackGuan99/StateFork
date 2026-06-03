# Checkpoint-lite Integration — StateFork change report

Cross-repo integration that exposes **StateFork's Checkpoint-lite** to the
**harbor** framework. This file is the authoritative report for **StateFork's**
side; the harbor repo has a matching `INTEGRATION_REPORT.md`.

> **Maintenance:** update this file *and* harbor's counterpart on **every**
> change to this integration. See `CLAUDE.md`.

## Design (one line)
Add an **HTTP RPC control server** (`interface/rpc.py`) wrapping the existing
`controller.create_env_manager` — i.e. the "RPC interface" the README listed as
TODO. StateFork's existing code/interfaces are **unchanged**; everything here is
additive.

## Files

### New
- **`interface/rpc.py`** (258 lines) — FastAPI control server.
  - **11 endpoints:** `GET /health`; `POST /sessions`;
    `POST /sessions/{id}/snapshot`; `.../restore`; `.../fork`; `.../exec`;
    `.../upload`; `.../download`; `GET /sessions/{id}/snapshots`;
    `.../tree`; `DELETE /sessions/{id}`.
  - **14 Pydantic models** (request/response).
  - `_Session` / `_Registry` (multi-session registry + per-session lock);
    `_require_work_dir` / `_host_path` — `/upload` & `/download` write/read the
    session's OverlayFS `work_dir` **directly** (filesystem-layer, like
    `docker cp`; no exec/base64 fallback); `main()` entrypoint
    (`python -m interface.rpc`).
- **`tests/test_rpc.py`** (160 lines) — 13 tests (`create_env_manager` faked; work_dir transfer against a temp dir).
- **`conftest.py`** (10 lines) — puts the repo root on `sys.path` for pytest.
- **`CLAUDE.md`** (agent guide).

### Modified
- **`interface/README.md`** — the RPC section "to be implemented" → full
  endpoint documentation.

### NOT changed (touched during exploration, then reverted → net zero)
`controller/__init__.py`, `controller/ckptlite_env_manager.py`. No lazy-import or
`$CHECKPOINT_LITE_BIN` changes remain — original code is intact.

## Interfaces
- **Added:** the HTTP RPC interface (11 endpoints) + `main()` entrypoint.
- **Removed / modified existing:** none.

## How to run
```bash
(sudo) python3 -m interface.rpc --host 0.0.0.0 --port 8088   # from repo root
```
Single worker (in-memory session registry). harbor's `checkpoint-lite`
environment (`transport="rpc"`) is the HTTP client.

## harbor side (counterpart)
harbor's `CheckpointLiteEnvironment` (out-of-tree, via `import_path`) drives this
two ways, both through `controller.create_env_manager`: `transport="rpc"` (HTTP
to this server) and `transport="local"` (`import controller` in-process). See
harbor's `INTEGRATION_REPORT.md`.

## Verification
13/13 tests pass (real `pytest`, WSL Ubuntu).

## Status
**NOT committed / NOT pushed** (per the user's request) — all changes are in the
working tree only.
