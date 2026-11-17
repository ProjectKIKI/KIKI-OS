"""Run a GTK fixture after a real X11 setup handshake, retaining diagnostics."""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid


def receive(sock, count):
    data = b""
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise OSError("X11 setup connection closed")
        data += part
    return data


def connect_display(number, deadline, server):
    """Keep this connection alive so the server cannot reset between probes."""
    last_error = None
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError("Xvfb exited before X11 became ready")
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(min(0.25, max(0.01, deadline - time.monotonic())))
        try:
            client.connect("/tmp/.X11-unix/X" + str(number))
            client.sendall(struct.pack("<BBHHHHH", ord("l"), 0, 11, 0, 0, 0, 0))
            header = receive(client, 8)
            if header[0] != 1:
                raise OSError("X11 setup was rejected")
            receive(client, struct.unpack_from("<H", header, 6)[0] * 4)
            return client
        except OSError as exc:
            last_error = exc
            client.close()
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    raise TimeoutError("X11 setup readiness timed out: " + str(last_error))


def run(command, artifacts, startup_timeout=10, command_timeout=60):
    artifacts.mkdir(parents=True, exist_ok=True)
    tag = "xvfb-" + uuid.uuid4().hex
    log_path = artifacts / (tag + ".log")
    record_path = artifacts / (tag + ".json")
    record = {"ready": False, "command": Path(command[0]).name}
    server = client = application = None
    read_fd, write_fd = os.pipe()
    code = 125
    try:
        with log_path.open("wb") as log:
            server = subprocess.Popen(
                ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1920x1080x24",
                 "-nolisten", "tcp", "-ac"],
                pass_fds=(write_fd,), stdout=log, stderr=log,
            )
            record["server_pid"] = server.pid
            os.close(write_fd)
            write_fd = None
            deadline = time.monotonic() + startup_timeout
            number = b""
            with selectors.DefaultSelector() as selector:
                selector.register(read_fd, selectors.EVENT_READ)
                while b"\n" not in number:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError("Xvfb display-number notification timed out")
                    part = os.read(read_fd, 64)
                    if not part or len(number) + len(part) > 64:
                        raise RuntimeError("Invalid Xvfb display-number notification")
                    number += part
            number = number.strip()
            if not number.isdigit():
                raise RuntimeError("Invalid Xvfb display number")
            display = int(number)
            client = connect_display(display, deadline, server)
            record.update(ready=True, display=display)
            env = dict(os.environ, DISPLAY=":" + str(display), GDK_BACKEND="x11")
            try:
                application = subprocess.Popen(command, env=env, start_new_session=True)
                record["application_pid"] = application.pid
                code = application.wait(timeout=command_timeout)
            except subprocess.TimeoutExpired:
                record["error"] = "GTK fixture exceeded command timeout"
                code = 124
    except KeyboardInterrupt:
        record["error"] = "GTK fixture interrupted"
        code = 130
    except (OSError, RuntimeError, TimeoutError) as exc:
        record["error"] = str(exc)
        print("Xvfb fixture setup failed: " + str(exc), file=sys.stderr)
    finally:
        if application is not None and application.poll() is None:
            os.killpg(application.pid, signal.SIGTERM)
            try:
                application.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(application.pid, signal.SIGKILL)
                application.wait()
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        if client is not None:
            client.close()
        if server is not None:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
            record["server_exit"] = server.returncode
        record["exit"] = code
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        if code and log_path.exists():
            print(log_path.read_text(errors="replace")[-8192:], file=sys.stderr)
            print("Xvfb diagnostics: " + str(record_path), file=sys.stderr)
    return code if code >= 0 else 128 - code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--startup-timeout", type=float, default=10)
    parser.add_argument("--command-timeout", type=float, default=60)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.startup_timeout <= 0 or args.command_timeout <= 0:
        parser.error("a command and positive timeouts are required")
    def terminate(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    if args.artifacts:
        return run(command, args.artifacts, args.startup_timeout, args.command_timeout)
    temporary = Path(tempfile.mkdtemp(prefix="kiki-xvfb-"))
    return run(command, temporary, args.startup_timeout, args.command_timeout)


if __name__ == "__main__":
    sys.exit(main())
