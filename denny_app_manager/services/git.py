from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal


def run_git(repo: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def inspect_git_repo(repo: Path) -> dict:
    root = run_git(repo, "rev-parse", "--show-toplevel")
    if root.returncode:
        return {"repository": False, "message": "不是 Git 仓库"}

    branch_result = run_git(repo, "branch", "--show-current")
    branch = branch_result.stdout.strip() or "(detached HEAD)"
    upstream_result = run_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    dirty = bool(run_git(repo, "status", "--porcelain").stdout.strip())
    if upstream_result.returncode:
        return {
            "repository": True, "upstream": False, "branch": branch,
            "ahead": 0, "behind": 0, "dirty": dirty,
            "message": f"{branch} · 未配置上游",
        }

    upstream = upstream_result.stdout.strip()
    counts = run_git(repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    if counts.returncode:
        return {"repository": True, "upstream": False, "branch": branch, "message": counts.stderr.strip()}
    ahead, behind = (int(value) for value in counts.stdout.split())
    relation = f"↑{ahead} ↓{behind}" if ahead or behind else "已同步"
    return {
        "repository": True, "upstream": True, "branch": branch,
        "ahead": ahead, "behind": behind, "dirty": dirty,
        "message": f"{branch} · {relation}" + (" · 有未提交改动" if dirty else ""),
    }


class GitStatusSignals(QObject):
    completed = Signal(str, dict)


class GitStatusTask(QRunnable):
    def __init__(self, app_id: str, repo: Path):
        super().__init__()
        self.app_id = app_id
        self.repo = repo
        self.signals = GitStatusSignals()

    def run(self) -> None:
        try:
            result = inspect_git_repo(self.repo)
        except Exception as exc:
            result = {"repository": False, "message": f"Git 状态检查失败：{exc}"}
        self.signals.completed.emit(self.app_id, result)


class GitActionSignals(QObject):
    completed = Signal(str, str, dict)


class GitActionTask(QRunnable):
    def __init__(self, app_id: str, action: str, repo: Path):
        super().__init__()
        self.app_id = app_id
        self.action = action
        self.repo = repo
        self.signals = GitActionSignals()

    def _upstream(self) -> str:
        result = run_git(self.repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        if result.returncode:
            raise RuntimeError("当前分支没有配置上游远端分支")
        return result.stdout.strip()

    def _counts(self, upstream: str) -> tuple[int, int]:
        result = run_git(self.repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "无法比较本地与远端提交")
        return tuple(int(value) for value in result.stdout.split())

    def run(self) -> None:
        lines: list[str] = []
        success = False
        try:
            upstream = self._upstream()
            if self.action == "fetch_rebase":
                fetch = run_git(self.repo, "fetch", "--prune", timeout=600)
                lines.extend(part for part in (fetch.stdout.strip(), fetch.stderr.strip()) if part)
                if fetch.returncode:
                    raise RuntimeError("Fetch 失败")
                ahead, behind = self._counts(upstream)
                if behind == 0:
                    lines.append("远端没有新提交。" if ahead == 0 else f"远端没有新提交；本地有 {ahead} 个待推送提交。")
                elif run_git(self.repo, "status", "--porcelain").stdout.strip():
                    lines.append(f"已 Fetch，远端有 {behind} 个新提交；工作区有未提交改动，为保护当前文件，暂不自动 Rebase。")
                else:
                    rebase = run_git(self.repo, "rebase", upstream, timeout=600)
                    lines.extend(part for part in (rebase.stdout.strip(), rebase.stderr.strip()) if part)
                    if rebase.returncode:
                        raise RuntimeError("Rebase 未完成；请查看日志中的冲突信息并解决后继续。")
                    lines.append(f"已 Rebase {behind} 个远端新提交。")
                success = True
            elif self.action == "push":
                ahead, _ = self._counts(upstream)
                if ahead == 0:
                    lines.append("没有待推送的提交。")
                else:
                    push = run_git(self.repo, "push", timeout=600)
                    lines.extend(part for part in (push.stdout.strip(), push.stderr.strip()) if part)
                    if push.returncode:
                        raise RuntimeError("Push 失败")
                    lines.append(f"已 Push {ahead} 个本地提交。")
                success = True
        except Exception as exc:
            lines.append(str(exc))
        self.signals.completed.emit(self.app_id, self.action, {"success": success, "lines": lines})
