from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from denny_app_manager.config import PROJECTS_ROOT
from denny_app_manager.services.git import GitActionTask, GitStatusTask


class GitController(QObject):
    status_updated = Signal(str, dict, bool)
    log_received = Signal(str, str)

    def __init__(self, configs: list[dict], parent: QObject | None = None):
        super().__init__(parent)
        self.configs = configs
        self.statuses: dict[str, dict] = {}
        self.status_tasks: dict[str, GitStatusTask] = {}
        self.action_tasks: dict[str, GitActionTask] = {}
        self.refresh_after_action: set[str] = set()
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.refresh)

    def start_monitoring(self) -> None:
        self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        for config in self.configs:
            app_id = config["id"]
            if app_id in self.status_tasks or app_id in self.action_tasks:
                continue
            task = GitStatusTask(app_id, PROJECTS_ROOT / config["project"])
            task.signals.completed.connect(self._status_received)
            self.status_tasks[app_id] = task
            QThreadPool.globalInstance().start(task)

    def _status_received(self, app_id: str, status: dict) -> None:
        self.status_tasks.pop(app_id, None)
        self.statuses[app_id] = status
        self.status_updated.emit(app_id, status, app_id in self.action_tasks)
        if app_id in self.refresh_after_action and app_id not in self.action_tasks:
            self.refresh_after_action.discard(app_id)
            QTimer.singleShot(100, self.refresh)

    def fetch_rebase(self, app_id: str) -> None:
        self._start_action(app_id, "fetch_rebase")

    def push(self, app_id: str) -> None:
        self._start_action(app_id, "push")

    def _start_action(self, app_id: str, action: str) -> None:
        if app_id in self.action_tasks:
            return
        status = self.statuses.get(app_id, {})
        if not status.get("repository") or not status.get("upstream"):
            return
        if action == "push" and int(status.get("ahead", 0)) <= 0:
            return
        self.log_received.emit(app_id, f"\n[{action}] 开始 · {status.get('branch', '')}")
        self.status_updated.emit(app_id, status, True)
        task = GitActionTask(app_id, action, PROJECTS_ROOT / self._config(app_id)["project"])
        task.signals.completed.connect(self._action_finished)
        self.action_tasks[app_id] = task
        QThreadPool.globalInstance().start(task)

    def _action_finished(self, app_id: str, action: str, result: dict) -> None:
        self.action_tasks.pop(app_id, None)
        for line in result.get("lines", []):
            self.log_received.emit(app_id, line)
        if not result.get("success"):
            self.log_received.emit(app_id, "操作未完成。")
        if app_id in self.status_tasks:
            self.refresh_after_action.add(app_id)
        self.refresh()

    def _config(self, app_id: str) -> dict:
        return next(config for config in self.configs if config["id"] == app_id)
