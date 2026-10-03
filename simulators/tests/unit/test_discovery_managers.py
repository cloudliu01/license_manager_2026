"""Unit tests for host-wide lmgrd discovery (monitor --discovery auto)."""

import subprocess
import time

from license_manager_simulators.monitor.topology import (
    _cmdline_is_lmgrd,
    discover_managers,
)


def test_cmdline_predicate():
    assert _cmdline_is_lmgrd(b"/cad/hes/license/lmgrd\0-c\0x.dat\0")
    assert _cmdline_is_lmgrd(b"lmgrd\0")
    assert _cmdline_is_lmgrd(b"/opt/flexlm/lmgrd11.18.1\0-l\0log\0")
    assert not _cmdline_is_lmgrd(b"python3\0-m\0license_manager_simulators.lmgrd.cli\0")
    assert not _cmdline_is_lmgrd(b"vendmock\0-T\0host\0")
    # prefix rule: versioned installs match, lmgrd-named wrappers would too
    assert _cmdline_is_lmgrd(b"/usr/bin/lmgrd_wrapper.sh\0")
    assert not _cmdline_is_lmgrd(b"")
    assert not _cmdline_is_lmgrd(b"\0lmgrd\0")  # empty argv0


def test_cmdline_basename_rule_not_substring():
    # a python script merely NAMED in the args never matches
    assert not _cmdline_is_lmgrd(b"bash\0-c\0tail -f lmgrd.log\0")


def test_discover_managers_finds_argv0_renamed_process():
    proc = subprocess.Popen(["/bin/bash", "-c", "exec -a lmgrd sleep 30"])
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if proc.pid in discover_managers():
                break
            time.sleep(0.05)
        assert proc.pid in discover_managers()
    finally:
        proc.kill()
        proc.wait()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if proc.pid not in discover_managers():
            break
        time.sleep(0.05)
    assert proc.pid not in discover_managers()


def test_discover_managers_excludes_self_and_python_trees():
    import os
    assert os.getpid() not in discover_managers()
