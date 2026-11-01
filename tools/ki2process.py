"""빌드 전용 프로세스 그룹을 종료하고 로그 수집을 끝냅니다."""
import os
import signal
import subprocess
import threading


class BuildCancelled(Exception):
    pass


def terminate_tree(proc):
    if os.name == 'posix':
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    else:
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)


def watch(proc, cancel, finished):
    while not finished.wait(0.05):
        if cancel.is_set():
            terminate_tree(proc)
            return


def watcher(proc, cancel):
    finished = threading.Event()
    thread = threading.Thread(target=watch, args=(proc, cancel, finished), daemon=True)
    thread.start()
    return finished, thread
