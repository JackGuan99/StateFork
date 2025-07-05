import subprocess
import time
import uuid
import logging
from typing import Optional, Literal
from .base_env_manager import EnvironmentManager, SnapshotNode

BackendType = Literal["Docker", "Podman"]

def get_backend_tool(backend: BackendType) -> tuple[str, str, logging.Logger]:
    """
    Returns the command, name, and logger for the specified backend.
    :param backend: The backend type, either "Docker" or "Podman".
    :return: A tuple containing the command to run, the name of the backend, and a logger instance.
    """
    if backend == "Docker":
        return "docker", "Docker", logging.getLogger(f"EnvManager.Docker")
    elif backend == "Podman":
        return "podman", "Podman", logging.getLogger(f"EnvManager.Podman")
    else:
        raise ValueError(f"Unsupported backend: {backend}")


class ContainerAttachManager(EnvironmentManager):
    def __init__(self, backend: BackendType, container_name: str, base_image: str):
        self.BACKEND_CMD, self.BACKEND_NAME, self.logger = get_backend_tool(backend)
        super().__init__(backend_name=self.BACKEND_NAME)
        self.container_name = container_name
        self.image_prefix = "statefork-app"
        self.snapshots["base"] = base_image

        # Init the Tree Graph
        self.snapshot_graph["base"] = SnapshotNode(snapshot_id="base", parent_id=None)
        self.current_snapshot_id = "base"
        self.last_snapshot_id = "base"


    def _core_snapshot(self) -> tuple[Optional[str], float]:
        snapshot_id = str(uuid.uuid4())[:8]
        image_name = f"{self.image_prefix}:{snapshot_id}"

        start = time.time()
        subprocess.run([self.BACKEND_CMD, "commit", self.container_name, image_name], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elapsed = time.time() - start

        self.snapshots[snapshot_id] = image_name

        return snapshot_id, elapsed

    def _core_create_env(self, snapshot_id: str) -> tuple[Optional[str], float]:
        image_name = self.snapshots.get(snapshot_id)
        if not image_name:
            self.logger.warning(f"Snapshot ID {snapshot_id} not found.")
            return None, 0.0

        # Stop & remove existing container if running
        subprocess.run([self.BACKEND_CMD, "rm", "-f", self.container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        start = time.time()
        subprocess.run([
            self.BACKEND_CMD, "run", "-d", "--rm",
            "--name", self.container_name,
            "-p", "8000:8000",
            "-v", "/tmp:/tmp",
            image_name
        ], check=True)
        elapsed = time.time() - start

        return self.container_name, elapsed

    def _core_cleanup(self):
        self.logger.info(f"Cleaning up {self.BACKEND_NAME} container '{self.container_name}'")
        subprocess.run([self.BACKEND_CMD, "rm", "-f", self.container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.logger.info(f"Cleaning up {self.BACKEND_NAME} images...")
        for snapshot_id in list(self.snapshots.keys()):
            image_name = self.snapshots[snapshot_id]
            subprocess.run([self.BACKEND_CMD, "rmi", image_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            del self.snapshots[snapshot_id]


class ContainerBuildManager(ContainerAttachManager):
    def __init__(self, backend: BackendType, base_image: str = "statefork-app:base", dockerfile_dir: str = "."):
        backend_cmd, backend_name, logger = get_backend_tool(backend)
        logger.info(f"Building base {backend_name} image '{base_image}' from directory '{dockerfile_dir}'...")
        subprocess.run([backend_cmd, "build", "-t", base_image, dockerfile_dir], check=True)

        super().__init__(backend=backend, container_name="statefork_active", base_image=base_image)

        logger.info("Creating initial environment from base image...")
        res, _ = self._core_create_env("base")
        if res is None:
            raise RuntimeError("Failed to create initial environment from base image.")
