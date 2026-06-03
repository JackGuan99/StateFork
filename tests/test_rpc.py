"""Tests for the StateFork RPC server (interface/rpc.py).

Checkpoint-lite / CRIU cannot run here, so these tests drive the route
functions directly with a fake EnvironmentManager, and exercise the work_dir
file-transfer against a real temp directory standing in for the session's
OverlayFS work_dir.
"""

import base64
import io
import tarfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from interface import rpc


class FakeManager:
    """Minimal stand-in for controller.EnvironmentManager."""

    def __init__(self):
        self.backend = "FakeBackend"
        self.current_snapshot = None
        self.work_dir = "/tmp/fake_work"
        self.cleaned = False
        self._snapshots: list[str] = []
        self._n = 0

    def snapshot(self):
        self._n += 1
        sid = f"snap{self._n}"
        self._snapshots.append(sid)
        self.current_snapshot = sid
        return sid

    def restore(self, snapshot_id):
        return snapshot_id in self._snapshots

    def create_env_from_snapshot(self, snapshot_id):
        return f"env-of-{snapshot_id}" if snapshot_id in self._snapshots else None

    def exec_command(self, command, timeout=None):
        return 0, "", ""

    def list_snapshots(self):
        return list(self._snapshots)

    def print_snapshot_tree(self):
        return "Snapshot Tree:\n" + "\n".join(self._snapshots)

    def cleanup(self):
        self.cleaned = True


@pytest.fixture
def fake():
    manager = FakeManager()
    rpc.registry = rpc._Registry()  # fresh registry per test
    with patch("interface.rpc.create_env_manager", return_value=manager):
        yield manager


def _new_session() -> str:
    return rpc.create_session(rpc.CreateSessionRequest()).session


def _session_with_work_dir(work_dir) -> str:
    sid = _new_session()
    rpc.registry.get(sid).work_dir = str(work_dir)
    return sid


# --------------------------------------------------------------------------- #
# Session lifecycle
# --------------------------------------------------------------------------- #
def test_create_session_returns_handle(fake):
    resp = rpc.create_session(rpc.CreateSessionRequest())
    assert resp.session
    assert resp.backend == "FakeBackend"
    assert resp.work_dir == "/tmp/fake_work"


def test_create_session_surfaces_backend_error():
    rpc.registry = rpc._Registry()
    with patch("interface.rpc.create_env_manager", side_effect=RuntimeError("boom")):
        with pytest.raises(HTTPException) as exc:
            rpc.create_session(rpc.CreateSessionRequest())
    assert exc.value.status_code == 400
    assert "boom" in exc.value.detail


def test_snapshot_restore_fork_flow(fake):
    sid = _new_session()
    snap = rpc.snapshot(sid)
    assert snap.snapshot_id == "snap1"
    assert rpc.list_snapshots(sid).snapshots == ["snap1"]
    assert rpc.restore(sid, rpc.RestoreRequest(snapshot_id="snap1")).ok is True
    assert rpc.fork(sid, rpc.ForkRequest(snapshot_id="snap1")).env == "env-of-snap1"


def test_restore_unknown_snapshot_404(fake):
    sid = _new_session()
    with pytest.raises(HTTPException) as exc:
        rpc.restore(sid, rpc.RestoreRequest(snapshot_id="missing"))
    assert exc.value.status_code == 404


def test_exec_returns_result(fake):
    sid = _new_session()
    resp = rpc.exec_command(sid, rpc.ExecRequest(command="echo hi"))
    assert resp.returncode == 0


def test_unknown_session_404(fake):
    with pytest.raises(HTTPException) as exc:
        rpc.snapshot("does-not-exist")
    assert exc.value.status_code == 404


def test_cleanup_drops_session(fake):
    sid = _new_session()
    assert rpc.cleanup(sid).ok is True
    assert fake.cleaned is True
    with pytest.raises(HTTPException) as exc:
        rpc.snapshot(sid)
    assert exc.value.status_code == 404


# --------------------------------------------------------------------------- #
# File transfer — direct work_dir read/write
# --------------------------------------------------------------------------- #
def test_upload_then_download_file(fake, tmp_path):
    sid = _session_with_work_dir(tmp_path)
    rpc.upload(
        sid,
        rpc.UploadRequest(
            path="/a.txt", content_b64=base64.b64encode(b"hello").decode(), untar=False
        ),
    )
    assert (tmp_path / "a.txt").read_bytes() == b"hello"
    resp = rpc.download(sid, rpc.DownloadRequest(path="/a.txt", is_dir=False))
    assert base64.b64decode(resp.content_b64) == b"hello"


def test_upload_creates_parent_dirs(fake, tmp_path):
    sid = _session_with_work_dir(tmp_path)
    rpc.upload(
        sid,
        rpc.UploadRequest(
            path="/sub/dir/b.txt",
            content_b64=base64.b64encode(b"x").decode(),
            untar=False,
        ),
    )
    assert (tmp_path / "sub" / "dir" / "b.txt").read_bytes() == b"x"


def test_upload_untar_and_download_dir(fake, tmp_path):
    sid = _session_with_work_dir(tmp_path)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        payload = b"data"
        info = tarfile.TarInfo("inner/f.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    rpc.upload(
        sid,
        rpc.UploadRequest(
            path="/d", content_b64=base64.b64encode(buf.getvalue()).decode(), untar=True
        ),
    )
    assert (tmp_path / "d" / "inner" / "f.txt").read_bytes() == b"data"

    resp = rpc.download(sid, rpc.DownloadRequest(path="/d", is_dir=True))
    with tarfile.open(
        fileobj=io.BytesIO(base64.b64decode(resp.content_b64)), mode="r:gz"
    ) as tar:
        assert any(name.endswith("f.txt") for name in tar.getnames())


def test_upload_without_work_dir_400(fake):
    sid = _new_session()
    rpc.registry.get(sid).work_dir = None
    with pytest.raises(HTTPException) as exc:
        rpc.upload(sid, rpc.UploadRequest(path="/a", content_b64="", untar=False))
    assert exc.value.status_code == 400


def test_path_escape_rejected(fake, tmp_path):
    sid = _session_with_work_dir(tmp_path)
    with pytest.raises(HTTPException) as exc:
        rpc.download(sid, rpc.DownloadRequest(path="/../../etc/passwd", is_dir=False))
    assert exc.value.status_code == 400


# --------------------------------------------------------------------------- #
# Optional: full ASGI smoke test (needs httpx for starlette's TestClient)
# --------------------------------------------------------------------------- #
def test_health_via_testclient():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    client = TestClient(rpc.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
