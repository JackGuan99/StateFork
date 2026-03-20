from __future__ import annotations

import logging
import subprocess
import time
import uuid
from typing import Optional, List
from .base_env_manager import EnvironmentManager, SnapshotNode
from decider import Decider

logger = logging.getLogger("EnvManager.GVisor")

class GvisorAttachManager(EnvironmentManager):
    def __init__(self,
                 container_name: str,
                 base_image: str,
                 extra_args: Optional[List[str]] = None,
                 decider: Optional[Decider] = None,
                 ):
        """
        Initialize a gVisor-based environment.

        :param container_name: Name of the running container to attach to.
        :param base_image: Base image to use for the environment.
            Example: "ubuntu:latest" or "statefork:base".
        :param extra_args: Additional command-line args passed during container startup.
            Example: ["-v", "/tmp:/tmp"]
        """
        # TODO: set logger?
        super().__init__(backend_name="gVisor", decider=decider)
        self.container_name = container_name
        self.extra_args = extra_args or []

        sid, _ = self._core_snapshot()
        if sid is None:
            raise RuntimeError("Failed to create initial snapshot.")

        # Init the Tree Graph
        self.snapshot_graph[sid] = SnapshotNode(snapshot_id=sid, parent_id=None)
        self.current_snapshot_id = sid
        self.last_snapshot_id = sid

        # TODO: Attach image calculator?


    def _core_snapshot(self) -> tuple[Optional[str], float]:
        snapshot_id = str(uuid.uuid4())[:8]
        image_name = f"{self.image_prefix}:{snapshot_id}"

        start = time.time()
        # TODO: Run `docker checkpoint create self.container_name image_name`
        # subprocess.run([...], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elapsed = time.time() - start

        self.snapshots[snapshot_id] = image_name

        return snapshot_id, elapsed

    def _core_create_env(self, snapshot_id: str) -> tuple[Optional[str], float]:
        image_name = self.snapshots.get(snapshot_id)
        if not image_name:
            logger.warning(f"Snapshot ID {snapshot_id} not found.")
            return None, 0.0

        # TODO: Do we need to stop & remove existing container if running
        # subprocess.run([...], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # TODO: Run `docker start --checkpoint image_name self.container_name`
        cmd = [...]
        logger.debug(f"Launching container with command: {' '.join(cmd)}")

        start = time.time()
        subprocess.run(cmd, stdout=subprocess.DEVNULL, check=True)
        elapsed = time.time() - start

        return self.container_name, elapsed

    def _core_cleanup(self):
        # TODO: How to cleanup resources?
        logger.info(f"Cleaning up gVisor container '{self.container_name}'")
        # subprocess.run(["docker", "rm", "-f", self.container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Cleaning up gVisor images...")
        for snapshot_id in list(self.snapshots.keys()):
            image_name = self.snapshots[snapshot_id]
            # subprocess.run(["docker", "rmi", image_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            del self.snapshots[snapshot_id]

    def _core_exec(self, command, timeout=None):
        # TODO: Not sure how to do exec in gVisor, guess is the same as Docker's
        if isinstance(command, list):
            cmd = ["docker", "exec", self.container_name] + command
        else:
            cmd = ["docker", "exec", self.container_name, "bash", "-c", command]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return result.returncode, result.stdout, result.stderr


class GvisorBuildManager(GvisorAttachManager):
    def __init__(self,
                 dockerfile_dir: str = ".",
                 base_image: str = None,
                 extra_args: Optional[List[str]] = None,
                 decider: Optional[Decider] = None,
                 ):
        """
        Initialize a gVisor-based environment by building from a Dockerfile.

        :param dockerfile_dir: Path to the directory containing the Dockerfile.
            Example: "/home/user/projects/myapp/"
        :param base_image: Base image to use for building the container.
            Example: "python:3.10-slim"
        :param extra_args: Additional command-line args passed during container startup.
            Example: ["-v", "/tmp:/tmp"]
        """
        if base_image is None:
            base_image = f"statefork_{str(uuid.uuid4())[:4]}:base"

        if extra_args is None:
            extra_args = ["-v", "/tmp:/tmp"]

        # TODO: set logger?
        logger.info(f"Building base gVisor image '{base_image}' from directory '{dockerfile_dir}'...")
        subprocess.run(["docker", "build", "-t", base_image, dockerfile_dir], stdout=subprocess.DEVNULL, check=True)

        logger.info("Creating initial environment from base image...")
        cmd = ["docker", "run", "-d", "--runtime", "runsc", "--network", "host", "--name", self.container_name] + self.extra_args + [base_image]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError:
            raise RuntimeError("Failed to create initial environment from base image.")

        super().__init__(container_name="statefork_active", base_image=base_image, extra_args=extra_args, decider=decider)
