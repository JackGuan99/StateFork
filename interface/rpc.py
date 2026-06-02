"""StateFork RPC interface.

A thin HTTP control plane over the :class:`controller.EnvironmentManager`
backends (in particular the Checkpoint-lite backend), so remote clients can
drive snapshot / restore / fork / exec / cleanup without a local Python
import or a co-located shell.

This is the "RPC Interface" referenced in ``interface/README.md``. It wraps
:func:`controller.create_env_manager`; every backend that the factory knows
about is therefore reachable over HTTP, but the default ``method`` is
``ckpt_build`` (Checkpoint-lite).

Run it (from the repository root, alongside the ``checkpoint-lite`` binary)::

    (sudo) python3 -m interface.rpc --host 0.0.0.0 --port 8088
    # or: (sudo) uvicorn interface.rpc:app --host 0.0.0.0 --port 8088

Notes / assumptions
-------------------
* Sessions are held in an in-memory registry, so the server MUST run with a
  single worker process (the default of :func:`uvicorn.run` below).
* Operations on a single session are serialized with a per-session lock;
  interleaving snapshot/restore/exec on the same session is unsafe.
* File transfer (:func:`/upload` / :func:`/download`) is implemented through
  the backend's ``exec`` primitive (base64, chunked, ``tar`` for directories)
  so it is backend-agnostic. It assumes the backend executes commands through
  a POSIX shell (true for the container backends; Checkpoint-lite runs on
  Linux), and is intended for modest payloads rather than bulk data.
"""

from __future__ import annotations

import argparse
import base64
import logging
import posixpath
import shlex
import threading
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from controller import EnvironmentManager, create_env_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("interface.rpc")

# Largest base64 payload pushed through a single exec command. Kept well under
# typical ARG_MAX so chunked uploads stay within shell command-length limits.
_UPLOAD_CHUNK = 60_000


# --------------------------------------------------------------------------- #
# Session registry
# --------------------------------------------------------------------------- #
class _Session:
    def __init__(self, manager: EnvironmentManager):
        self.manager = manager
        self.lock = threading.Lock()


class _Registry:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._guard = threading.Lock()

    def add(self, manager: EnvironmentManager) -> str:
        sid = uuid.uuid4().hex[:12]
        with self._guard:
            self._sessions[sid] = _Session(manager)
        return sid

    def get(self, sid: str) -> _Session:
        with self._guard:
            session = self._sessions.get(sid)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Unknown session: {sid}")
        return session

    def pop(self, sid: str) -> _Session:
        with self._guard:
            session = self._sessions.pop(sid, None)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Unknown session: {sid}")
        return session

    def ids(self) -> list[str]:
        with self._guard:
            return list(self._sessions)


registry = _Registry()


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #
class CreateSessionRequest(BaseModel):
    method: str = "ckpt_build"
    kwargs: dict = Field(default_factory=dict)


class CreateSessionResponse(BaseModel):
    session: str
    backend: str
    current_snapshot: Optional[str] = None
    work_dir: Optional[str] = None


class SnapshotResponse(BaseModel):
    snapshot_id: str


class RestoreRequest(BaseModel):
    snapshot_id: str


class ForkRequest(BaseModel):
    snapshot_id: str


class ForkResponse(BaseModel):
    env: str


class OkResponse(BaseModel):
    ok: bool


class ExecRequest(BaseModel):
    command: str | list[str]
    timeout: Optional[float] = None


class ExecResponse(BaseModel):
    returncode: int
    stdout: str
    stderr: str


class SnapshotsResponse(BaseModel):
    snapshots: list[str]


class TreeResponse(BaseModel):
    tree: str


class UploadRequest(BaseModel):
    path: str
    content_b64: str
    # When true, ``content_b64`` is a .tar.gz extracted into ``path``.
    untar: bool = False


class DownloadRequest(BaseModel):
    path: str
    # When true, ``path`` is a directory streamed back as a .tar.gz.
    is_dir: bool = False


class DownloadResponse(BaseModel):
    content_b64: str


# --------------------------------------------------------------------------- #
# Exec-based file transfer helpers (backend-agnostic)
# --------------------------------------------------------------------------- #
def _exec(manager: EnvironmentManager, command: str, timeout: float | None = None):
    rc, out, err = manager.exec_command(command, timeout=timeout)
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"exec failed (rc={rc}) for {command!r}: {err or out}",
        )
    return out


def _write_file_via_exec(
    manager: EnvironmentManager, path: str, data: bytes, untar: bool
) -> None:
    target = f"/tmp/_sf_upload_{uuid.uuid4().hex}.tar.gz" if untar else path

    parent = posixpath.dirname(target)
    if parent:
        _exec(manager, f"mkdir -p {shlex.quote(parent)}")

    # Truncate, then append base64-decoded chunks. The base64 alphabet has no
    # single quotes, so single-quoting each chunk is safe.
    _exec(manager, f": > {shlex.quote(target)}")
    b64 = base64.b64encode(data).decode("ascii")
    for i in range(0, len(b64), _UPLOAD_CHUNK):
        chunk = b64[i : i + _UPLOAD_CHUNK]
        _exec(manager, f"printf '%s' '{chunk}' | base64 -d >> {shlex.quote(target)}")

    if untar:
        _exec(manager, f"mkdir -p {shlex.quote(path)}")
        _exec(
            manager,
            f"tar xzf {shlex.quote(target)} -C {shlex.quote(path)} "
            f"&& rm -f {shlex.quote(target)}",
        )


def _read_file_via_exec(manager: EnvironmentManager, path: str, is_dir: bool) -> bytes:
    if is_dir:
        out = _exec(manager, f"tar czf - -C {shlex.quote(path)} . | base64")
    else:
        out = _exec(manager, f"base64 {shlex.quote(path)}")
    # b64decode with validate=False discards the newlines `base64` inserts.
    return base64.b64decode(out)


# --------------------------------------------------------------------------- #
# FastAPI application
# --------------------------------------------------------------------------- #
app = FastAPI(
    title="StateFork RPC service",
    description="HTTP control plane for Checkpoint-lite (and other) backends.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "sessions": registry.ids()}


@app.post("/sessions", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    try:
        manager = create_env_manager(req.method, **req.kwargs)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - surface backend errors to the client
        logger.exception("Failed to create session")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sid = registry.add(manager)
    logger.info("Created session %s (%s)", sid, manager.backend)
    return CreateSessionResponse(
        session=sid,
        backend=manager.backend,
        current_snapshot=manager.current_snapshot,
        work_dir=getattr(manager, "work_dir", None),
    )


@app.post("/sessions/{sid}/snapshot", response_model=SnapshotResponse)
def snapshot(sid: str) -> SnapshotResponse:
    session = registry.get(sid)
    with session.lock:
        snapshot_id = session.manager.snapshot()
    if snapshot_id is None:
        raise HTTPException(status_code=500, detail="snapshot failed")
    return SnapshotResponse(snapshot_id=snapshot_id)


@app.post("/sessions/{sid}/restore", response_model=OkResponse)
def restore(sid: str, req: RestoreRequest) -> OkResponse:
    session = registry.get(sid)
    with session.lock:
        ok = session.manager.restore(req.snapshot_id)
    if not ok:
        raise HTTPException(
            status_code=404, detail=f"restore failed for {req.snapshot_id}"
        )
    return OkResponse(ok=True)


@app.post("/sessions/{sid}/fork", response_model=ForkResponse)
def fork(sid: str, req: ForkRequest) -> ForkResponse:
    """Create an environment from a snapshot (``create_env_from_snapshot``).

    Branching semantics are backend-defined: container backends spin up a new
    container, while the Checkpoint-lite backend restores the snapshot into the
    session.
    """
    session = registry.get(sid)
    with session.lock:
        env = session.manager.create_env_from_snapshot(req.snapshot_id)
    if env is None:
        raise HTTPException(
            status_code=404, detail=f"fork failed for {req.snapshot_id}"
        )
    return ForkResponse(env=env)


@app.post("/sessions/{sid}/exec", response_model=ExecResponse)
def exec_command(sid: str, req: ExecRequest) -> ExecResponse:
    session = registry.get(sid)
    with session.lock:
        rc, out, err = session.manager.exec_command(req.command, timeout=req.timeout)
    return ExecResponse(returncode=rc, stdout=out, stderr=err)


@app.get("/sessions/{sid}/snapshots", response_model=SnapshotsResponse)
def list_snapshots(sid: str) -> SnapshotsResponse:
    session = registry.get(sid)
    return SnapshotsResponse(snapshots=session.manager.list_snapshots())


@app.get("/sessions/{sid}/tree", response_model=TreeResponse)
def snapshot_tree(sid: str) -> TreeResponse:
    session = registry.get(sid)
    with session.lock:
        tree = session.manager.print_snapshot_tree()
    return TreeResponse(tree=tree)


@app.post("/sessions/{sid}/upload", response_model=OkResponse)
def upload(sid: str, req: UploadRequest) -> OkResponse:
    session = registry.get(sid)
    try:
        data = base64.b64decode(req.content_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid base64: {exc}") from exc
    with session.lock:
        _write_file_via_exec(session.manager, req.path, data, req.untar)
    return OkResponse(ok=True)


@app.post("/sessions/{sid}/download", response_model=DownloadResponse)
def download(sid: str, req: DownloadRequest) -> DownloadResponse:
    session = registry.get(sid)
    with session.lock:
        data = _read_file_via_exec(session.manager, req.path, req.is_dir)
    return DownloadResponse(content_b64=base64.b64encode(data).decode("ascii"))


@app.delete("/sessions/{sid}", response_model=OkResponse)
def cleanup(sid: str) -> OkResponse:
    session = registry.pop(sid)
    with session.lock:
        session.manager.cleanup()
    logger.info("Cleaned up session %s", sid)
    return OkResponse(ok=True)


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="StateFork RPC server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    # Single worker: the session registry is in-process state.
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
