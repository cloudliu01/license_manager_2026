import socket

import pytest
from license_manager_simulators.core.license_parser import parse_license_text
from license_manager_simulators.lmgrd.ports import reserve_ports


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _free_dynamic_port() -> int:
    for port in range(40000, 50001):
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
                return port
        except OSError:
            pass
    raise RuntimeError("No dynamic test port available")


def test_bind_explicit_and_implicit_daemon_with_actual_sockets():
    manager_port = _free_port()
    daemon_port = _free_port()
    while daemon_port == manager_port:
        daemon_port = _free_port()
    dynamic = _free_dynamic_port()
    config = parse_license_text(
        f"PORT {manager_port}\nDAEMON vend PORT {daemon_port}\nFEATURE a 1 DAEMON vend\nFEATURE b 2"
    )
    with reserve_ports(config, "127.0.0.1", candidates=[dynamic]) as sockets:
        assert sockets.manager.getsockname()[1] == manager_port
        assert sockets.daemons["vend"].getsockname()[1] == daemon_port
        assert sockets.daemons["default"].getsockname()[1] == dynamic
        with pytest.raises(OSError), socket.socket() as duplicate:
            duplicate.bind(("127.0.0.1", daemon_port))
    assert sockets.manager.fileno() == -1
    assert all(sock.fileno() == -1 for sock in sockets.daemons.values())


def test_busy_port_skipped_and_failure_closes_all_sockets():
    first, second = _free_dynamic_port(), None
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", first))
        occupied.listen()
        second = _free_dynamic_port()
        manager_port = _free_port()
        config = parse_license_text(f"PORT {manager_port}\nFEATURE a 1")
        with reserve_ports(config, "127.0.0.1", candidates=[first, second]) as sockets:
            assert sockets.daemons["default"].getsockname()[1] == second
        with pytest.raises(OSError, match="No free daemon port"):
            reserve_ports(config, "127.0.0.1", candidates=[first])
        # Atomic failure must release the manager port too.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", manager_port))


def test_fixed_port_collision_is_atomic():
    daemon_port = _free_port()
    manager_port = _free_port()
    while manager_port == daemon_port:
        manager_port = _free_port()
    config = parse_license_text(f"PORT {manager_port}\nDAEMON vend PORT {daemon_port}")
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", daemon_port))
        with pytest.raises(OSError):
            reserve_ports(config, "127.0.0.1")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", manager_port))
