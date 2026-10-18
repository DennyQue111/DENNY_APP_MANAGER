from __future__ import annotations

import os
import subprocess
import sys
import time
from codecs import getincrementaldecoder
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QPlainTextEdit


@dataclass
class ManagedService:
    process: QProcess
    port: int
    decoder: object


def find_executable(name: str) -> str:
    resolved = subprocess.run(["where.exe", name], capture_output=True, text=True, check=False)
    return resolved.stdout.splitlines()[0].strip() if resolved.stdout.strip() else name


def build_service_command(project_root: Path, service_config: dict, config: dict,
                          service_name: str, port: int) -> tuple[str, list[str], Path]:
    cwd = (project_root / service_config["cwd"]).resolve()
    python_candidates = [
        project_root / "backend" / "venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / "venv" / "Scripts" / "python.exe",
    ]
    python_path = next((path for path in python_candidates if path.is_file()), Path(sys.executable))
    values = {
        "port": str(port),
        "python": str(python_path),
        "backend_port": str(service_config.get("backend_port", config.get("backend_port", ""))),
    }
    command = [part.format(**values) for part in service_config["command"]]
    if command[0] == "npm":
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", find_executable("npm.cmd"), *command[1:]]
    return command[0], command[1:], cwd


def new_log_decoder():
    return getincrementaldecoder("utf-8")()


def stop_process_tree(process: QProcess) -> None:
    if process.state() == QProcess.NotRunning:
        return
    if sys.platform == "win32" and process.processId():
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.processId()), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        process.waitForFinished(1500)
        return
    process.terminate()
    deadline = time.monotonic() + 1.2
    while process.state() != QProcess.NotRunning and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.03)
    if process.state() != QProcess.NotRunning:
        process.kill()
        process.waitForFinished(1000)


def append_process_output(process: QProcess, log: QPlainTextEdit, decoder,
                          *, final: bool = False) -> None:
    raw = bytes(process.readAllStandardOutput())
    output = decoder.decode(raw, final=final)
    if output:
        log.moveCursor(log.textCursor().MoveOperation.End)
        log.insertPlainText(output)
        log.moveCursor(log.textCursor().MoveOperation.End)
