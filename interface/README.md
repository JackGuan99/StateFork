# StateFork Interfaces

## ⚙️ Interactive CLI Interface

### 1. Launch the Interactive Shell
```bash
(sudo) python3 -m interface.shell --method {method}
```
Currently supported methods:
- `docker` (default) - for Docker-based environments focused on filesystem snapshots
- `podman` - for Podman-based environments focused on filesystem snapshots
- `criu` - for CRIU-based environments focused on process state snapshots
- `hybrid` - for Podman+CRIU environments combining filesystem and process state snapshots
- `ckpt` - for our own [Checkpoint-lite](https://github.com/Alex-XJK/checkpoint-lite/) environments

### 2. Inside the Interactive Shell
After launching the shell with the desired method, you will see a prompt similar to this:
```
StateFork Container Manager - Interactive Shell
Commands: snapshot, restore <id>, step, tree, stats, history, storage, exit

StateFork > _
```
See the sample run screenshot below.

### 3. Common Commands
| Command	      | Description                                              |
|---------------|----------------------------------------------------------|
| snapshot	     | Take a snapshot of the current state                     |
| restore {id}	 | Roll back to a given snapshot ID                         |
| step	         | Snapshot and restore immediately to simulate progression |
| cmd {command} | Execute a shell command inside the managed environment   |
| tree	         | Show snapshot tree structure                             |
| stats	        | Show benchmarking results                                |
| history	      | Show operation history                                   |
| storage	      | Show storage usage and details                           |
| exit	         | Clean up and exit the manager                            |

### 📸 Sample Run
![Sample Run Screenshot](../docs/sample_run.png)


## 🚀 RPC Interface

An HTTP control plane (`interface/rpc.py`) exposes the `EnvironmentManager`
backends so remote clients can drive snapshot/restore/fork/exec/cleanup without
a local Python import or a co-located shell. This is what the
[harbor](https://github.com/harbor-framework/harbor) `checkpoint-lite`
environment talks to.

### Launch the server
```bash
# From the repository root, alongside the `checkpoint-lite` binary.
(sudo) python3 -m interface.rpc --host 0.0.0.0 --port 8088
# or: (sudo) uvicorn interface.rpc:app --host 0.0.0.0 --port 8088
```

The server keeps sessions in memory, so run it with a **single worker**.

### Endpoints
| Method & Path | Body | Description |
|---------------|------|-------------|
| `GET /health` | — | Liveness probe + active session IDs |
| `POST /sessions` | `{method?, kwargs?}` | Create a session (default `method="ckpt_build"`). Returns `{session, backend, current_snapshot, work_dir}` |
| `POST /sessions/{sid}/snapshot` | — | Take a snapshot. Returns `{snapshot_id}` |
| `POST /sessions/{sid}/restore` | `{snapshot_id}` | Restore the session to a snapshot |
| `POST /sessions/{sid}/fork` | `{snapshot_id}` | `create_env_from_snapshot` (branching; backend-defined) |
| `POST /sessions/{sid}/exec` | `{command, timeout?}` | Run a command. Returns `{returncode, stdout, stderr}` |
| `GET /sessions/{sid}/snapshots` | — | List snapshot IDs |
| `GET /sessions/{sid}/tree` | — | Snapshot tree (string) |
| `POST /sessions/{sid}/upload` | `{path, content_b64, untar?}` | Write a file (or extract a `.tar.gz`) into the session |
| `POST /sessions/{sid}/download` | `{path, is_dir?}` | Read a file (or `.tar.gz` of a directory) out of the session |
| `DELETE /sessions/{sid}` | — | Clean up and drop the session |

File transfer goes through the backend's `exec` primitive (base64, chunked,
`tar` for directories), so it is backend-agnostic but intended for modest
payloads rather than bulk data.