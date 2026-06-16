"""Tests for the StateFork one-shot Checkpoint-lite CLI (interface/cli.py).

The ``checkpoint-lite`` / ``waypoint`` binary and CRIU cannot run here, so these
tests mock the ``subprocess.run`` seam and assert that each subcommand issues
the right binary argv and surfaces output / exit codes correctly. This is the
CLI that harbor's ``CheckpointLiteEnvironment`` drives over ``subprocess``
(``python -m interface.cli ...``).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from interface import cli


def _cp(returncode=0, stdout="", stderr=""):
    """A stand-in for subprocess.CompletedProcess (only the read attrs)."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def run(monkeypatch):
    mock = MagicMock(return_value=_cp(0))
    monkeypatch.setattr(cli.subprocess, "run", mock)
    return mock


def _argv(run: MagicMock) -> list:
    return run.call_args.args[0]


# --------------------------------------------------------------------------- #
# create  (init / build)
# --------------------------------------------------------------------------- #
def test_create_defaults_to_build(run, capsys):
    run.return_value = _cp(0, stdout="sid123,/work,42\n")
    assert cli.main(["create", "/ctx"]) == 0
    assert _argv(run) == [cli._BIN, "build", "/ctx", "--quiet"]
    assert capsys.readouterr().out.strip() == "sid123,/work,42"


def test_create_no_build_uses_init(run, capsys):
    run.return_value = _cp(0, stdout="sid,/w\n")
    assert cli.main(["create", "/ctx", "--no-build"]) == 0
    assert _argv(run) == [cli._BIN, "init", "/ctx", "--quiet"]


def test_create_failure_returns_rc(run):
    run.return_value = _cp(2, stderr="boom")
    assert cli.main(["create", "/ctx"]) == 2


# --------------------------------------------------------------------------- #
# exec  (passes through stdout/stderr/returncode)
# --------------------------------------------------------------------------- #
def test_exec_passthrough(run, capsys):
    run.return_value = _cp(5, stdout="hi\n", stderr="warn")
    assert cli.main(["exec", "sess", "echo hi"]) == 5
    assert _argv(run) == [cli._BIN, "exec", "sess", "echo hi"]
    captured = capsys.readouterr()
    assert captured.out == "hi\n"
    assert captured.err == "warn"


# --------------------------------------------------------------------------- #
# snapshot  (create <session> <id> -2)
# --------------------------------------------------------------------------- #
def test_snapshot_generates_id_and_uses_pid_sentinel(run, capsys):
    assert cli.main(["snapshot", "sess"]) == 0
    argv = _argv(run)
    assert argv[:3] == [cli._BIN, "create", "sess"]
    snap_id = argv[3]
    assert argv[4] == str(cli._PID_NOT_PROVIDED) == "-2"
    # The generated id is echoed on stdout (harbor parses it).
    assert capsys.readouterr().out.strip() == snap_id
    assert len(snap_id) == 8


def test_snapshot_explicit_id(run, capsys):
    assert cli.main(["snapshot", "sess", "--id", "fixed"]) == 0
    assert _argv(run) == [cli._BIN, "create", "sess", "fixed", "-2"]
    assert capsys.readouterr().out.strip() == "fixed"


def test_snapshot_failure_returns_rc(run, capsys):
    run.return_value = _cp(1, stderr="criu failed")
    assert cli.main(["snapshot", "sess"]) == 1
    assert capsys.readouterr().out == ""  # no id printed on failure


# --------------------------------------------------------------------------- #
# restore / cleanup
# --------------------------------------------------------------------------- #
def test_restore(run):
    assert cli.main(["restore", "sess", "snap1"]) == 0
    assert _argv(run) == [cli._BIN, "restore", "sess", "snap1"]


def test_restore_failure_returns_rc(run):
    run.return_value = _cp(3, stderr="no such checkpoint")
    assert cli.main(["restore", "sess", "missing"]) == 3


def test_cleanup_force(run):
    assert cli.main(["cleanup", "sess", "--force"]) == 0
    assert _argv(run) == [cli._BIN, "cleanup", "sess", "--force"]


def test_cleanup_without_force(run):
    assert cli.main(["cleanup", "sess"]) == 0
    assert _argv(run) == [cli._BIN, "cleanup", "sess"]


# --------------------------------------------------------------------------- #
# argparse plumbing
# --------------------------------------------------------------------------- #
def test_pid_not_provided_matches_waypoint_sentinel():
    # Must equal waypoint's PidNotProvided / StateFork's PID_NOT_PROVIDED.
    assert cli._PID_NOT_PROVIDED == -2


def test_missing_subcommand_errors():
    with pytest.raises(SystemExit):
        cli.main([])
