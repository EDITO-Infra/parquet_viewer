from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from pathlib import Path

BACKEND_PORT = 8000
BACKEND_PID_FILE = ".parquet_viewer_backend.pid"


def _check_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"[error] Missing {label}: {path}")


def _build_frontend(root: Path) -> None:
    frontend_dir = root / "frontend"
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    if shutil.which(npm_cmd) is None:
        raise SystemExit(
            "[error] Node.js/npm is required to build the frontend. "
            "Install Node.js and run python main.py again."
        )

    node_modules = frontend_dir / "node_modules"
    if not node_modules.exists():
        print("[info] Installing frontend dependencies...")
        subprocess.run(
            [npm_cmd, "ci"],
            cwd=str(frontend_dir),
            check=True,
        )

    print("[info] Building frontend...")
    subprocess.run(
        [
            npm_cmd,
            "run",
            "build",
            "--",
            "--outDir",
            "../frontend_dist",
            "--emptyOutDir",
        ],
        cwd=str(frontend_dir),
        check=True,
    )


def _wait_for_http(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1):
                return
        except Exception as error:
            last_error = error
            time.sleep(0.2)
    raise SystemExit(f"[error] Timed out waiting for {url}: {last_error}")


def _stop_previous_backend(root: Path) -> bool:
    pid_file = root / BACKEND_PID_FILE
    pids: set[int] = set()

    if pid_file.exists():
        try:
            pids.add(int(pid_file.read_text(encoding="ascii").strip()))
        except (OSError, ValueError):
            pass

    if os.name == "nt":
        netstat = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in netstat.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 5 and fields[0].lower() == "tcp":
                local_address, state, pid = fields[1], fields[3], fields[4]
                if (
                    state.upper() == "LISTENING"
                    and local_address.rsplit(":", 1)[-1] == str(BACKEND_PORT)
                    and pid.isdigit()
                ):
                    pids.add(int(pid))

    for pid in pids:
        if pid == os.getpid():
            continue
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            print(f"[warning] Could not stop previous backend process {pid}.")
            continue

        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            except OSError:
                # Windows does not support signal 0; SIGTERM is synchronous
                # for the child process used by this launcher.
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    try:
        pid_file.unlink()
    except FileNotFoundError:
        pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", BACKEND_PORT))
        except OSError:
            return False
    return True


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    root = Path(__file__).resolve().parent
    _check_exists(root / "parquet_viewer" / "api.py", "backend entrypoint")
    _check_exists(root / "frontend" / "package.json", "frontend package.json")
    _check_exists(root / "frontend" / "package-lock.json", "frontend package-lock.json")
    preferred_port_available = _stop_previous_backend(root)
    _build_frontend(root)

    backend_port = BACKEND_PORT if preferred_port_available else _find_free_port()
    if backend_port != BACKEND_PORT:
        print(
            f"[warning] Port {BACKEND_PORT} is occupied by an old process; "
            f"using port {backend_port}."
        )
    backend_url = f"http://127.0.0.1:{backend_port}"
    print(f"[info] Starting application on {backend_url}")
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "parquet_viewer.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
        ],
        cwd=str(root),
    )
    (root / BACKEND_PID_FILE).write_text(str(backend.pid), encoding="ascii")

    print(f"[info] Backend PID: {backend.pid}")
    print(f"[info] Frontend: {backend_url}")
    print("[info] Press Ctrl+C to stop both.")

    try:
        _wait_for_http(f"{backend_url}/health")
        while True:
            code = backend.poll()
            if code is not None:
                return code
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n[info] Stopping services...")
    finally:
        if backend.poll() is None:
            backend.terminate()
        if backend.poll() is None:
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()
        try:
            (root / BACKEND_PID_FILE).unlink()
        except FileNotFoundError:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
