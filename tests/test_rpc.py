"""Tests for the StateFork RPC server (interface/rpc.py).

The Checkpoint-lite binary / CRIU cannot run here, so these tests drive the
route functions directly with a fake EnvironmentManager and exercise the
backend-agnostic exec-based file-transfer helpers.
"""

import base64
import shlex
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
        self.exec_log: list = []
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
        self.exec_log.append(command)
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
    # Fresh registry per test so session IDs don't leak across tests.
    rpc.registry = rpc._Registry()
    with patch("interface.rpc.create_env_manager", return_value=manager):
        yield manager


def _new_session():
    return rpc.create_session(rpc.CreateSessionRequest()).session


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
    assert "echo hi" in fake.exec_log


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
# Exec-based file transfer helpers
# --------------------------------------------------------------------------- #
def test_write_file_via_exec_chunks_and_decodes(fake):
    rpc._write_file_via_exec(fake, "/work/a.txt", b"hello world", untar=False)
    log = fake.exec_log
    assert any(cmd.startswith("mkdir -p ") and "/work" in cmd for cmd in log)
    assert any(cmd.startswith(": > ") for cmd in log)
    assert any("base64 -d >>" in cmd for cmd in log)


def test_write_file_via_exec_untar_extracts(fake):
    rpc._write_file_via_exec(fake, "/work/dir", b"tarbytes", untar=True)
    log = fake.exec_log
    needle = f"-C {shlex.quote('/work/dir')}"
    assert any(cmd.startswith("tar xzf ") and needle in cmd for cmd in log)


def test_read_file_via_exec_roundtrip():
    payload = b"some file contents"

    class ReadFake(FakeManager):
        def exec_command(self, command, timeout=None):
            self.exec_log.append(command)
            return 0, base64.b64encode(payload).decode(), ""

    manager = ReadFake()
    data = rpc._read_file_via_exec(manager, "/work/a.txt", is_dir=False)
    assert data == payload
    assert manager.exec_log[-1] == f"base64 {shlex.quote('/work/a.txt')}"


def test_read_file_dir_uses_tar():
    class ReadFake(FakeManager):
        def exec_command(self, command, timeout=None):
            self.exec_log.append(command)
            return 0, base64.b64encode(b"tar").decode(), ""

    manager = ReadFake()
    rpc._read_file_via_exec(manager, "/work/dir", is_dir=True)
    assert (
        manager.exec_log[-1]
        == f"tar czf - -C {shlex.quote('/work/dir')} . | base64"
    )


def test_exec_helper_raises_on_nonzero(fake):
    class FailFake(FakeManager):
        def exec_command(self, command, timeout=None):
            return 1, "", "nope"

    with pytest.raises(HTTPException) as exc:
        rpc._exec(FailFake(), "false")
    assert exc.value.status_code == 500


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
