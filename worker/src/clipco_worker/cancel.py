"""Cancellation of the active analysis job in this process: its media/speech child processes are stopped and its
in-flight inference request is disconnected (Ollama stops generating when its client goes away).

The queue runner calls cancel() when the creator cancels the active job (from any process); the job then unwinds
with Cancelled at its next step, publishing nothing.
"""

import contextlib
import socket
import subprocess
import threading


class Cancelled(BaseException):
    """The active job was cancelled. A BaseException, so per-clip failure handling never records it as a failure."""


_lock = threading.Lock()
_cancelled = threading.Event()
_children: set[subprocess.Popen] = set()
_connections: set = set()


def reset() -> None:
    _cancelled.clear()


def requested() -> bool:
    return _cancelled.is_set()


def check() -> None:
    if _cancelled.is_set():
        raise Cancelled()


def cancel() -> None:
    _cancelled.set()
    with _lock:
        children, connections = list(_children), list(_connections)
    for child in children:
        with contextlib.suppress(OSError):
            child.terminate()
    for conn in connections:
        with contextlib.suppress(OSError, AttributeError):
            conn.sock.shutdown(socket.SHUT_RDWR)
    for child in children:
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()


def run(args: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run that cancel() can stop. A child stopped by cancellation raises Cancelled."""
    check_cancelled = globals()["check"]
    check_cancelled()
    child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)
    with _lock:
        _children.add(child)
    try:
        out, err = child.communicate()
    finally:
        with _lock:
            _children.discard(child)
    check_cancelled()
    if check and child.returncode:
        raise subprocess.CalledProcessError(child.returncode, args, out, err)
    return subprocess.CompletedProcess(args, child.returncode, out, err)


@contextlib.contextmanager
def connection(conn):
    """Track an http.client connection so cancel() can disconnect it."""
    check()
    with _lock:
        _connections.add(conn)
    try:
        yield conn
    finally:
        with _lock:
            _connections.discard(conn)
