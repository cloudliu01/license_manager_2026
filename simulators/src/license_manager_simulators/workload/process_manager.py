from __future__ import annotations

import signal
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SimulatorWrappers:
    lmgrd: Path
    lmstat: Path


@dataclass
class LmgrdProcess:
    lmgrd_path: Path
    license_path: Path
    log_path: Path
    _proc: subprocess.Popen | None = field(default=None, init=False, repr=False)
    exit_status: int | None = field(default=None, init=False)

    def start(self) -> None:
        self._proc = subprocess.Popen(
            [str(self.lmgrd_path), "-c", str(self.license_path), "-l", str(self.log_path)]
        )

    def stop(self) -> None:
        if self._proc is None:
            return
        self._proc.send_signal(signal.SIGTERM)
        try:
            self.exit_status = self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self.exit_status = self._proc.wait(timeout=3)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def simulator_wrappers() -> SimulatorWrappers:
    root = Path(__file__).resolve().parents[3]
    return SimulatorWrappers(
        lmgrd=root / "wrappers" / "lmgrd",
        lmstat=root / "wrappers" / "lmstat",
    )
