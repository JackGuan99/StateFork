from .base_env_manager import EnvironmentManager
from .docker_env_manager import DockerAttachManager, DockerBuildManager
from .criu_env_manager import CRIUAttachManager, CRIULaunchManager
from .benchmark import BenchmarkStats

from typing import Literal, Optional, List, Union

EnvType = Literal["criu_launch", "criu_attach", "docker_build", "docker_attach"]

def create_env_manager(method: EnvType, **kwargs) -> EnvironmentManager:
    if method == "criu_launch":
        return CRIULaunchManager(
            work_dir=kwargs.get("work_dir", "/tmp/statefork_criu"),
            command=kwargs.get("command")
        )
    elif method == "criu_attach":
        return CRIUAttachManager(
            target_pid=kwargs["target_pid"],
            work_dir=kwargs.get("work_dir", "/tmp/statefork_criu")
        )
    elif method == "docker_build":
        return DockerBuildManager(
            base_image=kwargs.get("base_image", "statefork-app:latest"),
            dockerfile_dir=kwargs.get("dockerfile_dir", ".")
        )
    elif method == "docker_attach":
        return DockerAttachManager(
            container_name=kwargs["container_name"],
            base_image=kwargs.get("base_image", "statefork-app:latest")
        )
    else:
        raise ValueError(f"Unknown method: {method}")
