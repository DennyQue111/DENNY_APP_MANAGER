from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class AppCard(QFrame):
    start_requested = Signal(str)
    stop_requested = Signal(str)
    open_requested = Signal(str)
    fetch_rebase_requested = Signal(str)
    push_requested = Signal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.setObjectName("appCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.tabs = QTabWidget()
        self.service_statuses: dict[str, QLabel] = {}
        self.service_logs: dict[str, QPlainTextEdit] = {}
        self.git_log: QPlainTextEdit | None = None

        title = QLabel(config["name"])
        title.setObjectName("cardTitle")
        description = QLabel(config["description"])
        description.setObjectName("muted")
        self.status = QLabel("已停止")
        self.status.setObjectName("statusStopped")

        self.start_button = QPushButton("启动")
        self.stop_button = QPushButton("停止")
        self.open_button = QPushButton("打开页面")
        self.fetch_rebase_button = QPushButton("Fetch & Rebase")
        self.push_button = QPushButton("Push")
        self.stop_button.setEnabled(False)
        self.open_button.setEnabled("frontend" in config)
        self.fetch_rebase_button.setEnabled(False)
        self.push_button.setEnabled(False)
        self.push_button.setToolTip("只有当前分支存在尚未推送的提交时才可用。未提交文件需要先 commit。")

        self.start_button.clicked.connect(lambda: self.start_requested.emit(config["id"]))
        self.stop_button.clicked.connect(lambda: self.stop_requested.emit(config["id"]))
        self.open_button.clicked.connect(lambda: self.open_requested.emit(config["id"]))
        self.fetch_rebase_button.clicked.connect(lambda: self.fetch_rebase_requested.emit(config["id"]))
        self.push_button.clicked.connect(lambda: self.push_requested.emit(config["id"]))

        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.status)

        service_row = QHBoxLayout()
        for service_name in ("backend", "frontend"):
            if service_name not in config:
                continue
            label = QLabel(f"{service_name}: 检测中")
            label.setObjectName("serviceUnknown")
            self.service_statuses[service_name] = label
            service_row.addWidget(label)
            self._ensure_service_log(service_name, int(config[f"{service_name}_port"]))
        service_row.addStretch()

        buttons = QHBoxLayout()
        for button in (
            self.start_button,
            self.stop_button,
            self.open_button,
            self.fetch_rebase_button,
            self.push_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch()

        self.git_status = QLabel("Git: 检测中")
        self.git_status.setObjectName("muted")
        layout = QVBoxLayout(self)
        layout.addLayout(heading)
        layout.addWidget(description)
        layout.addLayout(service_row)
        layout.addLayout(buttons)
        layout.addWidget(self.git_status)
        layout.addWidget(self.tabs)

    def _ensure_service_log(self, name: str, port: int) -> QPlainTextEdit:
        if name in self.service_logs:
            return self.service_logs[name]
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 4, 0, 0)
        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setMaximumBlockCount(3000)
        log.setPlaceholderText("服务日志会显示在这里…")
        layout.addWidget(log)
        self.tabs.addTab(tab, f"{name} · {port}")
        self.service_logs[name] = log
        return log

    def append_service_log(self, name: str, text: str) -> None:
        log = self.service_logs.get(name)
        if log is None:
            return
        log.moveCursor(log.textCursor().MoveOperation.End)
        log.insertPlainText(text)
        log.moveCursor(log.textCursor().MoveOperation.End)

    def append_git_log(self, text: str) -> None:
        if self.git_log is None:
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(0, 4, 0, 0)
            self.git_log = QPlainTextEdit()
            self.git_log.setReadOnly(True)
            self.git_log.setMaximumBlockCount(2000)
            self.git_log.setPlaceholderText("Git 操作结果会显示在这里…")
            layout.addWidget(self.git_log)
            self.tabs.addTab(tab, "Git")
        self.git_log.appendPlainText(text)

    def set_service_status(self, service_name: str, text: str, active: bool) -> None:
        label = self.service_statuses.get(service_name)
        if label is None:
            return
        display = f"{service_name}: {text}"
        style_name = "serviceRunning" if active else "serviceStopped"
        if label.text() == display and label.objectName() == style_name:
            return
        label.setText(display)
        if label.objectName() != style_name:
            label.setObjectName(style_name)
            label.style().unpolish(label)
            label.style().polish(label)

    def set_runtime_status(self, status: dict) -> None:
        if status.get("stopping"):
            self._set_button_enabled(self.stop_button, False)
            self._set_button_enabled(self.start_button, False)
            self._set_status_text("正在停止…", True)
            return
        for name, state in status["services"].items():
            self.set_service_status(name, state["text"], state["listening"])
        self._set_button_enabled(self.start_button, status["can_start"])
        self._set_button_enabled(self.stop_button, status["can_stop"])
        self._set_button_enabled(self.open_button, "frontend" in self.config)
        self._set_status_text(status["message"], status["running"])

    def set_git_status(self, status: dict, busy: bool = False) -> None:
        message = status.get("message", "Git 状态未知")
        self.git_status.setText(f"Git: {message}" + (" · 操作中…" if busy else ""))
        has_upstream = bool(status.get("repository") and status.get("upstream"))
        self._set_button_enabled(self.fetch_rebase_button, has_upstream and not busy)
        push_ready = has_upstream and int(status.get("ahead", 0)) > 0 and not busy
        self._set_button_enabled(self.push_button, push_ready)
        style_name = "pushReady" if push_ready else "pushUnavailable"
        if self.push_button.objectName() != style_name:
            self.push_button.setObjectName(style_name)
            self.push_button.style().unpolish(self.push_button)
            self.push_button.style().polish(self.push_button)

    @staticmethod
    def _set_button_enabled(button: QPushButton, enabled: bool) -> None:
        if button.isEnabled() != enabled:
            button.setEnabled(enabled)

    def _set_status_text(self, text: str, running: bool) -> None:
        style_name = "statusRunning" if running else "statusStopped"
        if self.status.text() != text:
            self.status.setText(text)
        if self.status.objectName() != style_name:
            self.status.setObjectName(style_name)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
