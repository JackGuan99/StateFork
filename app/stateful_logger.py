import time
import os
import signal
import sys
from datetime import datetime

# Global state
counter = 0
log_path = "/tmp/criu_test_log.txt"
log_file = None
running = True

def graceful_shutdown(signum, frame):
    global running
    print(f"[PID {os.getpid()}] Caught signal {signum}, exiting gracefully...")
    running = False

def main():
    global counter, log_file

    # Open the log file in append mode (keeps FD open for CRIU)
    log_file = open(log_path, "a")

    pid = os.getpid()
    print(f"[PID {pid}] Starting stateful logger")
    log_file.write(f"[PID {pid}] Logging started\n")
    log_file.flush()

    # Trap SIGTERM/SIGINT for clean shutdown
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    while running:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [PID {pid}] Counter: {counter}\n"
        # print(log_entry.strip())
        log_file.write(log_entry)
        log_file.flush()

        counter += 1
        time.sleep(1)  # Slow enough to CRIU dump during run

    log_file.write(f"[PID {pid}] Exiting at counter {counter}\n")
    log_file.close()
    print(f"[PID {pid}] Done.")

if __name__ == "__main__":
    main()
