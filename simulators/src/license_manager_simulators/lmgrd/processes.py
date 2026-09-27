"""Internal daemon process lifecycle; deliberately no public wire protocol yet.

The wire format is blocked on annotated raw capture samples. This module only
establishes real child PIDs, socket ownership and read-only IPC snapshots.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Self

from license_manager_simulators.core.log_writer import FileLogWriter
from license_manager_simulators.core.models import LicenseConfig
from license_manager_simulators.lmgrd.ports import PortReservation, reserve_ports

MAX_IPC = 1 << 20


class WorkerUnavailable(RuntimeError):
    pass


def _send(channel: socket.socket, message: dict[str, Any]) -> None:
    data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(data) > MAX_IPC:
        raise ValueError("IPC message too large")
    channel.sendall(data)


def _receive(channel: socket.socket) -> dict[str, Any]:
    data = bytearray()
    while len(data) < MAX_IPC:
        byte = channel.recv(1)
        if not byte:
            raise WorkerUnavailable("Worker control channel closed")
        if byte == b"\n":
            try:
                result = json.loads(data)
            except (ValueError, UnicodeDecodeError) as exc:
                raise WorkerUnavailable("Malformed worker response") from exc
            if not isinstance(result, dict):
                raise WorkerUnavailable("Malformed worker response")
            return result
        data.extend(byte)
    raise WorkerUnavailable("Worker response too large")


class DaemonProcess:
    def __init__(self, process: subprocess.Popen[bytes], channel: socket.socket, name: str, port: int) -> None:
        self.process = process
        self.channel = channel
        self.name = name
        self.port = port
        self._lock = Lock()

    @property
    def pid(self) -> int:
        return self.process.pid

    def request(self, operation: str, **params: Any) -> dict[str, Any]:
        with self._lock:
            if self.process.poll() is not None:
                raise WorkerUnavailable(f"{self.name} exited")
            try:
                _send(self.channel, {"op": operation, **params})
                reply = _receive(self.channel)
            except (OSError, TimeoutError) as exc:
                raise WorkerUnavailable(f"{self.name} IPC unavailable") from exc
            if reply.get("error"):
                raise WorkerUnavailable(str(reply["error"]))
            return reply

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.request("stop")
            except WorkerUnavailable:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        else:
            self.process.wait()
        self.channel.close()


class ProcessGroup:
    """Bound manager socket plus actual daemon children. Not a public server.

    Caller owns this group and MUST close it. Manager TCP service must not report
    readiness until a separately approved wire adapter is installed.
    """

    def __init__(
        self, reservation: PortReservation, workers: dict[str, DaemonProcess],
        log_writer: FileLogWriter | None = None, log_channels: list[socket.socket] | None = None,
    ) -> None:
        self.reservation = reservation
        self.workers = workers
        self.log_writer = log_writer
        self.log_channels = log_channels or []
        self._log_lock = Lock()
        self._log_threads: list[Thread] = []

    def snapshot(self) -> dict[str, dict[str, Any]]:
        # A missing worker is an error, never an empty/zero license pool.
        return {name: worker.request("status")["status"] for name, worker in self.workers.items()}

    def close(self) -> None:
        for worker in self.workers.values():
            worker.close()
        for thread in self._log_threads:
            thread.join(timeout=2)
        for channel in self.log_channels:
            channel.close()
        self.reservation.close()
        if self.log_writer:
            with self._log_lock:
                self.log_writer.shutdown()
                self.log_writer.close()

    def _drain_log(self, channel: socket.socket) -> None:
        try:
            with channel.makefile("r", encoding="utf-8") as stream:
                for line in stream:
                    with self._log_lock:
                        if self.log_writer:
                            self.log_writer.write_raw_lines([line.rstrip("\n")])
        except (OSError, ValueError):
            pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def start_process_group(
    config: LicenseConfig, license_path: str, host: str = "127.0.0.1", *,
    candidates: list[int] | None = None, log_path: str | None = None,
) -> ProcessGroup:
    """Launch children with an inherited bound socket and private control FD."""
    reservation = reserve_ports(config, host, candidates=candidates)
    workers: dict[str, DaemonProcess] = {}
    log_channels: list[socket.socket] = []
    writer = FileLogWriter(log_path) if log_path else None
    group = ProcessGroup(reservation, workers, writer, log_channels)
    # pytest's pythonpath setting is not exported to subprocesses.
    src = str(Path(__file__).resolve().parents[2])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [src, env.get("PYTHONPATH")]))
    try:
        for name, listener in reservation.daemons.items():
            parent, child = socket.socketpair()
            log_parent, log_child = socket.socketpair()
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "license_manager_simulators.lmgrd.worker", license_path, name,
                     str(listener.fileno()), str(child.fileno()), str(log_child.fileno())],
                    pass_fds=(listener.fileno(), child.fileno(), log_child.fileno()),
                    env=env,
                )
            except BaseException:
                parent.close()
                log_parent.close()
                raise
            finally:
                child.close()
                log_child.close()
            log_channels.append(log_parent)
            thread = Thread(target=group._drain_log, args=(log_parent,), daemon=True)
            thread.start()
            group._log_threads.append(thread)
            parent.settimeout(3)
            worker = DaemonProcess(proc, parent, name, listener.getsockname()[1])
            workers[name] = worker
            ready = worker.request("ready")
            if ready.get("pid") != worker.pid or ready.get("port") != worker.port:
                raise WorkerUnavailable(f"{name} readiness mismatch")
            # Parent MUST release this reference: /proc now attributes it to the child.
            listener.close()
        return group
    except BaseException:
        group.close()
        raise
