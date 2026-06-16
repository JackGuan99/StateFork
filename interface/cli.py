"""StateFork one-shot Checkpoint-lite CLI.

A small, *scriptable* (non-interactive) command-line front-end to the
Checkpoint-lite / ``waypoint`` binary, suitable for being driven per-operation
via ``subprocess`` — the way harbor's ``CheckpointLiteEnvironment`` uses it
(like ``docker compose`` is shelled out to). It matches Checkpoint-lite's native
model: ``waypoint`` persists session state on disk and reloads it per command,
so each invocation is stateless.

Run from the repository root, alongside the ``checkpoint-lite`` binary
(override its path with ``$CHECKPOINT_LITE_BIN``)::

    (sudo) python3 -m interface.cli create /path/to/context --build
    (sudo) python3 -m interface.cli exec    <session> "echo hi"
    (sudo) python3 -m interface.cli snapshot <session>
    (sudo) python3 -m interface.cli restore  <session> <checkpoint-id>
    (sudo) python3 -m interface.cli cleanup  <session> --force

Commands map 1:1 onto the underlying binary (``init``/``build``, ``exec``,
``create``, ``restore``, ``cleanup``).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid

# Path to the checkpoint-lite / waypoint binary. Defaults to the cwd-relative
# `./checkpoint-lite` (run this CLI from the repo root, or set the env var).
_BIN = os.environ.get("CHECKPOINT_LITE_BIN", "./checkpoint-lite")

# "PID not provided" sentinel — matches waypoint's `PidNotProvided` and
# StateFork's `CheckpointLiteAttachManager.PID_NOT_PROVIDED`. Tells `create` to
# checkpoint the managed shell session (or skip memory if there is none).
_PID_NOT_PROVIDED = -2


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([_BIN, *args], **kwargs)


def cmd_create(a: argparse.Namespace) -> int:
    # build (Dockerfile/buildah sandbox) or init (overlay over a workspace).
    sub = "build" if a.build else "init"
    proc = _run([sub, a.dir, "--quiet"], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    # waypoint prints "sid,workdir[,bash_pid]"; pass it straight through.
    sys.stdout.write(proc.stdout.strip() + "\n")
    return 0


def cmd_exec(a: argparse.Namespace) -> int:
    proc = _run(["exec", a.session, a.command], capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


def cmd_snapshot(a: argparse.Namespace) -> int:
    snapshot_id = a.id or uuid.uuid4().hex[:8]
    proc = _run(
        ["create", a.session, snapshot_id, str(_PID_NOT_PROVIDED)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        return proc.returncode
    sys.stdout.write(snapshot_id + "\n")
    return 0


def cmd_restore(a: argparse.Namespace) -> int:
    proc = _run(["restore", a.session, a.snapshot], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
    return proc.returncode


def cmd_cleanup(a: argparse.Namespace) -> int:
    args = ["cleanup", a.session] + (["--force"] if a.force else [])
    proc = _run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
    return proc.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="interface.cli",
        description="One-shot Checkpoint-lite CLI (StateFork).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="Create a session from a context dir")
    c.add_argument("dir")
    c.add_argument("--build", dest="build", action="store_true", default=True)
    c.add_argument("--no-build", dest="build", action="store_false")
    c.set_defaults(func=cmd_create)

    e = sub.add_parser("exec", help="Run a command in the session")
    e.add_argument("session")
    e.add_argument("command")
    e.set_defaults(func=cmd_exec)

    s = sub.add_parser("snapshot", help="Create a checkpoint; prints its id")
    s.add_argument("session")
    s.add_argument("--id", default=None)
    s.set_defaults(func=cmd_snapshot)

    r = sub.add_parser("restore", help="Restore a checkpoint")
    r.add_argument("session")
    r.add_argument("snapshot")
    r.set_defaults(func=cmd_restore)

    cl = sub.add_parser("cleanup", help="Clean up a session")
    cl.add_argument("session")
    cl.add_argument("--force", action="store_true")
    cl.set_defaults(func=cmd_cleanup)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
