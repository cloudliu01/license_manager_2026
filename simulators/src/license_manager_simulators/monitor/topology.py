"""Discover actual Linux child PIDs and TCP listener socket ownership."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Listener:
    pid: int
    port: int
    daemon: str | None
    inode: int


def _children(pid: int) -> list[int]:
    path = Path(f"/proc/{pid}/task/{pid}/children")
    return [int(child) for child in path.read_text().split()]


def _listener_inodes() -> dict[int, int]:
    """Inode -> TCP LISTEN port (IPv4 and IPv6; capture itself is IPv4)."""
    result = {}
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in Path(table).read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == "0A":
                result[int(fields[9])] = int(fields[1].split(":")[1], 16)
    return result


def _daemon_name(pid: int) -> str | None:
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        marker = b"license_manager_simulators.lmgrd.worker"
        idx = args.index(marker)
        return args[idx + 2].decode("utf-8")
    except (OSError, ValueError, IndexError, UnicodeDecodeError):
        return None


def discover(manager_pid: int) -> dict[int, Listener]:
    """Return port -> owner; fail closed if the requested PID no longer exists."""
    if not Path(f"/proc/{manager_pid}").exists():
        raise ProcessLookupError(manager_pid)
    listeners = _listener_inodes()
    result: dict[int, Listener] = {}
    for pid in [manager_pid, *_children(manager_pid)]:
        try:
            name = None if pid == manager_pid else _daemon_name(pid)
            for path in Path(f"/proc/{pid}/fd").iterdir():
                try:
                    target = os.readlink(path)
                except OSError:
                    continue
                if not (target.startswith("socket:[") and target.endswith("]")):
                    continue
                inode = int(target[8:-1])
                port = listeners.get(inode)
                if port is not None:
                    result[port] = Listener(pid, port, name, inode)
        except (FileNotFoundError, PermissionError):
            continue
    return result
