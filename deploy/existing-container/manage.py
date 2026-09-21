import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time


def process_start(pid: int) -> str:
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def run(home: Path) -> None:
    import uvicorn
    from peerlink.hub import create_app

    os.umask(0o077)
    runtime = home / "run"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "hub.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid = os.getpid()
        record = runtime / "hub.pid.json"
        record.write_text(json.dumps({"pid": pid, "start": process_start(pid)}))
        try:
            uvicorn.run(
                create_app(str(home / "data" / "hub.db")),
                host=os.environ.get("PEERLINK_BIND", "0.0.0.0"),
                port=int(os.environ.get("PEERLINK_PORT", "18083")),
            )
        finally:
            record.unlink(missing_ok=True)


def stop(home: Path) -> None:
    record = home / "run" / "hub.pid.json"
    if not record.exists():
        return
    entry = json.loads(record.read_text())
    pid = int(entry["pid"])
    try:
        if process_start(pid) != entry["start"]:
            raise RuntimeError("PID has been reused; refusing to signal")
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if os.fsencode(sys.argv[0]) not in command or b"run" not in command:
            raise RuntimeError("Process is not this Peerlink manager; refusing to signal")
        os.kill(pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        return
    for attempt in range(100):
        try:
            if process_start(pid) != entry["start"]:
                return
        except FileNotFoundError:
            return
        time.sleep(0.2)
    raise RuntimeError("Peerlink did not stop within 20 seconds")


if __name__ == "__main__":
    home = Path(os.environ["PEERLINK_HOME"])
    if sys.argv[1:] == ["run"]:
        run(home)
    elif sys.argv[1:] == ["stop"]:
        stop(home)
    else:
        raise SystemExit("Usage: manage.py run|stop")
