import os
import socket
import sys
from pathlib import Path

import pytest
from license_manager_simulators.core.license_parser import parse_license_file
from license_manager_simulators.lmgrd.processes import (
    WorkerUnavailable,
    start_process_group,
)
from license_manager_simulators.monitor.topology import discover


def _socket_inode(port: int) -> str:
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        if int(fields[1].split(":")[1], 16) == port and fields[3] == "0A":
            return f"socket:[{fields[9]}]"
    raise AssertionError(f"No TCP listener on port {port}")


def _fds(pid: int) -> set[str]:
    result = set()
    for fd in (Path("/proc") / str(pid) / "fd").iterdir():
        try:
            result.add(os.readlink(fd))
        except FileNotFoundError:
            pass
    return result


def _free_dynamic_ports(count: int) -> list[int]:
    result = []
    for port in range(40000, 50001):
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
            result.append(port)
        except OSError:
            pass
        if len(result) == count:
            return result
    raise RuntimeError("Not enough dynamic test ports")


@pytest.mark.skipif(sys.platform != "linux", reason="PID/socket ownership assertions require Linux /proc")
def test_separate_children_own_listener_and_snapshot(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        manager_port = probe.getsockname()[1]
    path = tmp_path / "license.txt"
    path.write_text(
        f"PORT {manager_port}\nSERVER_NAME lic_server\nDAEMON vend_a\nDAEMON vend_b\n"
        "FEATURE alpha 2 DAEMON vend_a\nFEATURE beta 3 DAEMON vend_b\n"
    )
    config = parse_license_file(str(path))
    with start_process_group(config, str(path), candidates=_free_dynamic_ports(2)) as group:
        children = list(group.workers.values())
        assert len({os.getpid(), *[worker.pid for worker in children]}) == 3
        for worker in children:
            # stat's second field is the parent PID (comm is parenthesized).
            stat = Path(f"/proc/{worker.pid}/stat").read_text().split(") ")[1].split()
            assert int(stat[1]) == os.getpid()
            inode = _socket_inode(worker.port)
            assert inode in _fds(worker.pid)
            assert inode not in _fds(os.getpid())
        observed = discover(os.getpid())
        assert observed[manager_port].pid == os.getpid()
        assert {observed[worker.port].pid for worker in children} == {worker.pid for worker in children}
        assert {observed[worker.port].daemon for worker in children} == {"vend_a", "vend_b"}
        snapshots = group.snapshot()
        assert [(row["feature"], row["total"]) for row in snapshots["vend_a"]["features"]] == [("alpha", 2)]
        assert [(row["feature"], row["total"]) for row in snapshots["vend_b"]["features"]] == [("beta", 3)]
        first = children[0]
        first.process.kill()
        first.process.wait(timeout=3)
        with pytest.raises(WorkerUnavailable):
            group.snapshot()  # unavailable, never silently reset to zero
    for worker in children:
        assert worker.process.poll() is not None
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", manager_port))
