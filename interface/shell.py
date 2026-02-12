import argparse
import logging

from controller import create_env_manager
from decider import RandomDecider, AlwaysTrueDecider, AlwaysFalseDecider


AVAILABLE_COMMANDS = [
    "snapshot",
    "restore <id>",
    "step",
    "cmd <command>",
    "tree",
    "stats",
    "history",
    "storage",
    "exit",
]


# -------- Backend Mapping --------
BACKEND_MAP = {
    "docker": "docker_build",
    "podman": "podman_build",
    "criu": "criu_build",
    "hybrid": "hybrid_build",
    "ckpt": "ckpt_build",
}


# -------- Decider Mapping --------
DECIDER_MAP = {
    "random": RandomDecider,
    "always_true": AlwaysTrueDecider,
    "always_false": AlwaysFalseDecider,
}


def build_manager(method: str, decider_name: str):
    method_key = BACKEND_MAP[method]
    decider_cls = DECIDER_MAP[decider_name]
    decider_instance = decider_cls()

    return create_env_manager(
        method_key,
        decider=decider_instance
    )


def interactive_shell(manager):
    print("==========================================")
    print("StateFork Container Manager - Interactive Shell")
    print(f"Using {manager.__class__.__name__} with {manager.backend} backend")
    print("")
    print(f"Available commands: {', '.join(AVAILABLE_COMMANDS)}")

    while True:
        cmd = input("\nStateFork > ").strip()

        if cmd == "snapshot":
            sid = manager.snapshot()
            print(f"Snapshot created: {sid}")

        elif cmd.startswith("restore"):
            _, _, sid = cmd.partition(" ")
            if not sid:
                print("Usage: restore <snapshot_id>")
                continue

            ok = manager.restore(sid)
            print(f"Restored to snapshot {sid}" if ok else f"Snapshot {sid} not found.")

        elif cmd == "step":
            sid = manager.snapshot()
            container = manager.create_env_from_snapshot(sid)
            print(
                f"Stepped to new container with snapshot {sid}"
                if container else
                "Failed to create new container from snapshot."
            )

        elif cmd.startswith("cmd"):
            _, _, command_text = cmd.partition(" ")
            if not command_text:
                print("Usage: cmd <command>")
                continue

            rc, out, err = manager.exec_command(command_text)

            print(f"Return code: {rc}")
            if out:
                print("--- stdout ---")
                print(out)
            if err:
                print("--- stderr ---")
                print(err)

        elif cmd == "tree":
            print(manager.print_snapshot_tree())

        elif cmd == "stats":
            print(manager.stats.print_stats())

        elif cmd == "history":
            print(manager.stats.print_history())

        elif cmd == "storage":
            print(manager.stats.print_size_details())

        elif cmd == "exit":
            print(manager.stats.print_stats())
            print("Cleaning up resources...")
            manager.cleanup()
            break

        else:
            print(f"Unknown command: {cmd}")
            print(f"Available commands: {', '.join(AVAILABLE_COMMANDS)}")


def main():
    parser = argparse.ArgumentParser(description="Environment Manager Launcher")

    parser.add_argument(
        "--method",
        choices=BACKEND_MAP.keys(),
        default="docker",
        help="Choose the environment manager backend"
    )

    parser.add_argument(
        "--decider",
        choices=DECIDER_MAP.keys(),
        default="random",
        help="Choose snapshot decision strategy"
    )

    args = parser.parse_args()

    manager = build_manager(args.method, args.decider)
    interactive_shell(manager)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
