from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QProcess


def _vscode_executable() -> Path | None:
    candidates: list[Path] = []
    for env_name, suffix in (
        ("LOCALAPPDATA", Path("Programs") / "Microsoft VS Code" / "Code.exe"),
        ("ProgramFiles", Path("Microsoft VS Code") / "Code.exe"),
        ("ProgramFiles(x86)", Path("Microsoft VS Code") / "Code.exe"),
    ):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / suffix)
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    command = shutil.which("code.exe")
    if command:
        return Path(command)
    return None


def open_project_in_vscode(project_path: Path) -> tuple[bool, str]:
    project_path = project_path.resolve()
    if not project_path.is_dir():
        return False, f"工程目录不存在：{project_path}"

    executable = _vscode_executable()
    if executable:
        result = QProcess.startDetached(str(executable), ["--reuse-window", str(project_path)])
        started = result[0] if isinstance(result, tuple) else result
        return (True, "") if started else (False, "VS Code 启动失败。")

    command_script = shutil.which("code")
    if command_script:
        command = subprocess.list2cmdline([command_script, "--reuse-window", str(project_path)])
        result = QProcess.startDetached(
            os.environ.get("COMSPEC", "cmd.exe"),
            ["/d", "/s", "/c", f'"{command}"'],
        )
        started = result[0] if isinstance(result, tuple) else result
        return (True, "") if started else (False, "VS Code 命令启动失败。")

    return False, "找不到 VS Code。请安装 VS Code，或将 code 命令加入 PATH。"
