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
    # lmgrd tree this listener belongs to (None when constructed ad hoc)
    manager_pid: int | None = None


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
    """Simulator worker daemons carry the feature name after the worker marker;
    real FlexLM vendor daemons (e.g. vendor00) fall back to their argv[0] base
    name so listeners stay attributable.
    """
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        marker = b"license_manager_simulators.lmgrd.worker"
        idx = args.index(marker)
        return args[idx + 2].decode("utf-8")
    except (OSError, ValueError, IndexError, UnicodeDecodeError):
        pass
    try:
        argv0 = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[0]
        return Path(argv0.decode("utf-8", "replace")).name or None
    except (OSError, IndexError):
        return None


def discover(manager_pid: int) -> dict[int, Listener]:
    """Return port -> owner; fail closed if the requested PID no longer exists.

    Real FlexLM servers fork the vendor daemon from lmgrd, so both processes
    hold the same listening sockets. The manager is iterated first and keeps
    the port entry (first owner wins) so the caller's manager-PID sanity
    check still holds; exclusive child ports are still attributed to the
    child with its daemon name.
    """
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
                if port is not None and port not in result:
                    result[port] = Listener(pid, port, name, inode, manager_pid)
        except (FileNotFoundError, PermissionError):
            continue
    return result


def _cmdline_is_lmgrd(raw: bytes) -> bool:
    """True when a /proc cmdline's argv0 is an lmgrd binary (basename starts
    with 'lmgrd', covering version-suffixed installs). Vendor daemons and
    simulator trees (python argv0) never match."""
    parts = raw.split(b"\0")
    if not parts or not parts[0]:
        return False
    name = Path(parts[0].decode("utf-8", "replace")).name
    return name.startswith("lmgrd")


def discover_managers() -> list[int]:
    """All lmgrd tree roots on this host, found by scanning /proc cmdlines.

    Only argv0 basenames starting with 'lmgrd' qualify; the monitor itself,
    vendor daemons and python-based simulators are never matched. Sorted for
    deterministic startup logs.
    """
    managers: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue  # vanished between listing and reading
        if _cmdline_is_lmgrd(raw):
            managers.append(int(entry.name))
    return sorted(managers)
