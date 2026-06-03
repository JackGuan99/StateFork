"""StateFork RPC interface.

A thin HTTP control plane over the :class:`controller.EnvironmentManager`
backends (in particular the Checkpoint-lite backend), so remote clients can
drive snapshot / restore / fork / exec / cleanup / file-transfer without a local
Python import or a co-located shell.

This is the "RPC Interface" referenced in ``interface/README.md``. It wraps
:func:`controller.create_env_manager`; the default ``method`` is ``ckpt_build``
(Checkpoint-lite).

Run it (from the repository root, alongside the ``checkpoint-lite`` binary)::

    (sudo) python3 -m interface.rpc --host 0.0.0.0 --port 8088
    # or: (sudo) uvicorn interface.rpc:app --host 0.0.0.0 --port 8088

Notes / assumptions
-------------------
* Sessions are held in an in-memory registry, so the server MUST run with a
  single worker process (the default of :func:`uvicorn.run` below).
* Operations on a single session are serialized with a per-session lock.
* File transfer (:func:`/upload` / :func:`/download`) writes/reads the
  session's OverlayFS ``work_dir`` directly on this host (filesystem-layer,
  like ``docker cp``) — the server is co-located with the session. The
  in-sandbox path is mapped to ``<work_dir>/<path>``, so it assumes a
  build/rootfs session whose ``work_dir`` is the sandbox root.
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import tarfile
import threading
import uuid
from io import BytesIO
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from controller import EnvironmentManager, create_env_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("interface.rpc")


# --------------------------------------------------------------------------- #
# Session registry
# --------------------------------------------------------------------------- #
class _Session:
    def __init__(self, manager: EnvironmentManager, work_dir: Optional[str] = None):
        self.manager = manager
        self.work_dir = work_dir
        self.lock = threading.Lock()


class _Registry:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._guard = threading.Lock()

    def add(self, manager: EnvironmentManager, work_dir: Optional[str] = None) -> str:
        sid = uuid.uuid4().hex[:12]
        with self._guard:
            self._sessions[sid] = _Session(manager, work_dir)
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
# Direct work_dir file transfer (filesystem-layer, like `docker cp`)
# --------------------------------------------------------------------------- #
def _require_work_dir(session: _Session) -> str:
    if not session.work_dir:
        raise HTTPException(
            status_code=400,
            detail="session has no work_dir; filesystem transfer unavailable "
            "(use a build/rootfs session).",
        )
    return session.work_dir


def _host_path(work_dir: str, path: str) -> str:
    """Map an in-sandbox path to its host path under work_dir, guarding ``..``."""
    base = os.path.realpath(work_dir)
    full = os.path.realpath(os.path.join(base, path.lstrip("/")))
    if full != base and not full.startswith(base + os.sep):
        raise HTTPException(status_code=400, detail=f"path escapes work_dir: {path}")
    return full


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

    work_dir = getattr(manager, "work_dir", None)
    sid = registry.add(manager, work_dir)
    logger.info("Created session %s (%s)", sid, manager.backend)
    return CreateSessionResponse(
        session=sid,
        backend=manager.backend,
        current_snapshot=manager.current_snapshot,
        work_dir=work_dir,
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

    Branching semantics are backend-defined.
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
    host_path = _host_path(_require_work_dir(session), req.path)
    try:
        data = base64.b64decode(req.content_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid base64: {exc}") from exc
    with session.lock:
        if req.untar:
            os.makedirs(host_path, exist_ok=True)
            with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as tar:
                tar.extractall(path=host_path, filter="data")
        else:
            os.makedirs(os.path.dirname(host_path) or "/", exist_ok=True)
            with open(host_path, "wb") as f:
                f.write(data)
    return OkResponse(ok=True)


@app.post("/sessions/{sid}/download", response_model=DownloadResponse)
def download(sid: str, req: DownloadRequest) -> DownloadResponse:
    session = registry.get(sid)
    host_path = _host_path(_require_work_dir(session), req.path)
    with session.lock:
        if req.is_dir:
            buffer = BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                tar.add(host_path, arcname=".")
            data = buffer.getvalue()
        else:
            with open(host_path, "rb") as f:
                data = f.read()
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
