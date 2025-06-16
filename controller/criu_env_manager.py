import os
import shutil
import subprocess
import time
import uuid
import logging
from typing import Optional
from base_env_manager import EnvironmentManager, SnapshotNode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CRIUEnvironmentManager(EnvironmentManager):
    def __init__(self, work_dir: str = "/tmp/statefork_criu"):
        super().__init__()
        self.work_dir = work_dir

        os.makedirs(self.work_dir, exist_ok=True)

        logger.info("Starting initial FastAPI app...")
        self.process = self.__start_app()
        if self.process.poll() is not None:
            raise RuntimeError("Failed to start the FastAPI app.")

        time.sleep(1)  # wait for app to initialize
        sid, _ = self._core_snapshot()
        if sid is None:
            raise RuntimeError("Failed to create initial snapshot.")

        self.snapshot_graph[sid] = SnapshotNode(snapshot_id=sid, parent_id=None)
        self.current_snapshot_id = sid
        self.last_snapshot_id = sid

    @staticmethod
    def __start_app() -> subprocess.Popen:
        return subprocess.Popen([
            "uvicorn", "app.api_server:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--no-access-log"
        ])

    def _core_snapshot(self) -> tuple[Optional[str], float]:
        snapshot_id = str(uuid.uuid4())[:8]
        snapshot_path = os.path.join(self.work_dir, snapshot_id)
        os.makedirs(snapshot_path, exist_ok=True)

        start = time.time()
        try:
            subprocess.run([
                "criu", "dump",
                "-t", str(self.process.pid),
                "--images-dir", snapshot_path,
                "--tcp-established",
                "--shell-job",
                "--leave-running"
            ], check=True)
            elapsed = time.time() - start
            self.snapshots[snapshot_id] = snapshot_path
            return snapshot_id, elapsed
        except subprocess.CalledProcessError as e:
            logger.error(f"CRIU snapshot failed: {e}")
            return None, 0.0

    def _core_create_env(self, snapshot_id: str) -> tuple[Optional[str], float]:
        snapshot_path = self.snapshots.get(snapshot_id)
        if not snapshot_path:
            logger.warning(f"Snapshot {snapshot_id} not found.")
            return None, 0.0

        # Terminate the existing FastAPI process
        if self.process:
            self.process.terminate()
            self.process.wait()

        start = time.time()
        try:
            self.process = subprocess.Popen([
                "criu", "restore",
                "--images-dir", snapshot_path,
                "--tcp-established",
                "--shell-job"
            ])
            elapsed = time.time() - start
            return snapshot_id, elapsed
        except subprocess.CalledProcessError as e:
            logger.error(f"CRIU restore failed: {e}")
            return None, 0.0

    def _core_restore(self, snapshot_id: str) -> tuple[bool, float]:
        start = time.time()
        result, _ = self._core_create_env(snapshot_id)
        elapsed = time.time() - start

        return result is not None, elapsed

    def _core_cleanup(self):
        if self.process:
            self.process.terminate()
            self.process.wait()
        shutil.rmtree(self.work_dir, ignore_errors=True)
