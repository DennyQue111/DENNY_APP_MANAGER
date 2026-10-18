from __future__ import annotations

import socket

from PySide6.QtCore import QObject, QRunnable, Signal


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) != 0


class PortScanSignals(QObject):
    completed = Signal(dict)


class PortScanTask(QRunnable):
    def __init__(self, ports: dict[tuple[str, str], int]):
        super().__init__()
        self.ports = ports
        self.signals = PortScanSignals()

    def run(self) -> None:
        results = {key: not port_available(port) for key, port in self.ports.items()}
        self.signals.completed.emit(results)
