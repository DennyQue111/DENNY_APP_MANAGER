from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QProcess, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "apps.json"


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def executable(name: str) -> str:
    resolved = subprocess.run(
        ["where.exe", name], capture_output=True, text=True, check=False
    )
    return resolved.stdout.splitlines()[0].strip() if resolved.stdout.strip() else name


class PortScanSignals(QObject):
    completed = Signal(dict)


class PortScanTask(QRunnable):
    def __init__(self, ports: dict[tuple[str, str], int]):
        super().__init__()
        self.ports = ports
        self.signals = PortScanSignals()

    def run(self) -> None:
        results = {}
        for key, port in self.ports.items():
            results[key] = not port_available(port)
        self.signals.completed.emit(results)


@dataclass
class Service:
    process: QProcess
    log: QPlainTextEdit
    status: QLabel
    port: int


class AppCard(QFrame):
    start_requested = Signal(str)
    stop_requested = Signal(str)
    open_requested = Signal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.setObjectName("appCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.services: dict[str, Service] = {}
        self.tabs = QTabWidget()

        title = QLabel(config["name"])
        title.setObjectName("cardTitle")
        description = QLabel(config["description"])
        description.setObjectName("muted")

        self.status = QLabel("已停止")
        self.status.setObjectName("statusStopped")
        self.service_statuses: dict[str, QLabel] = {}
        self.start_button = QPushButton("启动")
        self.stop_button = QPushButton("停止")
        self.open_button = QPushButton("打开页面")
        self.stop_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.start_button.clicked.connect(lambda: self.start_requested.emit(config["id"]))
        self.stop_button.clicked.connect(lambda: self.stop_requested.emit(config["id"]))
        self.open_button.clicked.connect(lambda: self.open_requested.emit(config["id"]))

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
        service_row.addStretch()

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.open_button)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(heading)
        layout.addWidget(description)
        layout.addLayout(service_row)
        layout.addLayout(buttons)
        layout.addWidget(self.tabs)

    def set_service_status(self, service_name: str, text: str, active: bool) -> None:
        label = self.service_statuses.get(service_name)
        if label is None:
            return
        display = f"{service_name}: {text}"
        object_name = "serviceRunning" if active else "serviceStopped"
        if label.text() == display and label.objectName() == object_name:
            return
        label.setText(display)
        if label.objectName() != object_name:
            label.setObjectName(object_name)
            label.style().unpolish(label)
            label.style().polish(label)

    def set_running(self, running: bool, message: str | None = None, *, can_stop: bool | None = None,
                    frontend_ready: bool | None = None, can_start: bool | None = None) -> None:
        start_enabled = (not running) if can_start is None else can_start
        stop_enabled = running if can_stop is None else can_stop
        open_enabled = (running if frontend_ready is None else frontend_ready) and "frontend" in self.config
        if self.start_button.isEnabled() != start_enabled:
            self.start_button.setEnabled(start_enabled)
        if self.stop_button.isEnabled() != stop_enabled:
            self.stop_button.setEnabled(stop_enabled)
        if self.open_button.isEnabled() != open_enabled:
            self.open_button.setEnabled(open_enabled)
        status_text = message or ("运行中" if running else "已停止")
        status_style = "statusRunning" if running else "statusStopped"
        if self.status.text() != status_text:
            self.status.setText(status_text)
        if self.status.objectName() != status_style:
            self.status.setObjectName(status_style)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)


class AppManager(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Denny App Manager")
        self.resize(1050, 850)
        self.configs = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["apps"]
        self.cards: dict[str, AppCard] = {}
        self.logs: dict[tuple[str, str], Service] = {}
        self.port_states: dict[tuple[str, str], bool] = {}
        self.scan_in_progress = False
        self.scan_task: PortScanTask | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(24, 22, 24, 22)
        root_layout.setSpacing(16)

        heading = QLabel("Denny App Manager")
        heading.setObjectName("pageTitle")
        subtitle = QLabel("本地服务控制台 · 独立端口 · 实时日志")
        subtitle.setObjectName("muted")
        root_layout.addWidget(heading)
        root_layout.addWidget(subtitle)

        info = QLabel("服务只监听本机。点击启动会运行项目的前后端，并在就绪后打开页面。")
        info.setObjectName("info")
        root_layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        list_widget = QWidget()
        cards_layout = QVBoxLayout(list_widget)
        cards_layout.setContentsMargins(2, 2, 10, 2)
        cards_layout.setSpacing(14)
        for config in self.configs:
            card = AppCard(config)
            card.start_requested.connect(self.start_app)
            card.stop_requested.connect(self.stop_app)
            card.open_requested.connect(self.open_app)
            self.cards[config["id"]] = card
            cards_layout.addWidget(card)
        cards_layout.addStretch()
        scroll.setWidget(list_widget)
        root_layout.addWidget(scroll, 1)

        self.setCentralWidget(central)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #10151d; color: #e5eaf2; font-family: 'Microsoft YaHei UI'; font-size: 10pt; }
            #pageTitle { font-size: 22pt; font-weight: 700; color: #f5f7fa; }
            #cardTitle { font-size: 13pt; font-weight: 650; }
            #muted { color: #98a5b5; }
            #info { color: #c3d7f2; background: #172337; padding: 12px; border-radius: 8px; }
            #appCard { background: #171e29; border: 1px solid #2a3545; border-radius: 12px; }
            QPushButton { background: #27364a; border: 1px solid #3a4b61; border-radius: 7px; padding: 8px 14px; }
            QPushButton:hover { background: #354a64; }
            QPushButton:disabled { color: #667487; background: #202833; }
            QTabWidget::pane { border: 1px solid #2b3746; border-radius: 6px; }
            QTabBar::tab { background: #202936; padding: 7px 12px; margin-right: 3px; }
            QTabBar::tab:selected { background: #34465d; }
            QPlainTextEdit { background: #0a0e13; color: #c9d7e6; border: none; font-family: Consolas; font-size: 9pt; }
            #statusRunning { color: #5ed6a2; font-weight: 650; padding: 3px 8px; }
            #statusStopped { color: #98a5b5; padding: 3px 8px; }
            #serviceRunning { color: #5ed6a2; padding: 3px 0; }
            #serviceStopped { color: #98a5b5; padding: 3px 0; }
            #serviceUnknown { color: #e5bd72; padding: 3px 0; }
        """)
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(2000)
        self.monitor_timer.timeout.connect(self._request_status_scan)
        self.monitor_timer.start()
        self._request_status_scan()

    def _service_command(self, config: dict, service_name: str, port: int) -> tuple[str, list[str], Path]:
        service_config = config[service_name]
        project_root = ROOT / config["project"]
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
            command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", executable("npm.cmd"), *command[1:]]
        return command[0], command[1:], cwd

    def _port_for(self, config: dict, service_name: str) -> int:
        return int(config[f"{service_name}_port"])

    def start_app(self, app_id: str) -> None:
        config = next(item for item in self.configs if item["id"] == app_id)
        card = self.cards[app_id]
        for service_name in ("backend", "frontend"):
            if service_name not in config:
                continue
            managed = self.logs.get((app_id, service_name))
            if managed and managed.process.state() != QProcess.NotRunning:
                continue
            port = self._port_for(config, service_name)
            if self.port_states.get((app_id, service_name), False):
                self._append_log(app_id, service_name, f"端口 {port} 已有服务监听，将监控现有服务。")
        for service_name in ("backend", "frontend"):
            if service_name in config:
                managed = self.logs.get((app_id, service_name))
                port = self._port_for(config, service_name)
                if (managed and managed.process.state() != QProcess.NotRunning) or self.port_states.get((app_id, service_name), False):
                    continue
                QTimer.singleShot(0 if service_name == "backend" else 800, lambda n=service_name: self._start_service(config, n))
        if "frontend" in config and self.port_states.get((app_id, "frontend"), False):
            self.open_app(app_id)
        self._apply_statuses(self.port_states)

    def _start_service(self, config: dict, service_name: str) -> None:
        app_id = config["id"]
        card = self.cards[app_id]
        port = self._port_for(config, service_name)
        key = (app_id, service_name)
        if key in self.logs and self.logs[key].process.state() != QProcess.NotRunning:
            return
        command, arguments, cwd = self._service_command(config, service_name, port)
        if not cwd.is_dir():
            self._append_log(app_id, service_name, f"工作目录不存在：{cwd}\n")
            card.set_running(False, "启动失败")
            return
        process = QProcess(self)
        process.setWorkingDirectory(str(cwd))
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.setProgram(command)
        process.setArguments(arguments)
        if service_name == "frontend":
            env = process.processEnvironment()
            env.insert("PORT", str(port))
            env.insert("DENNY_BACKEND_PORT", str(config[service_name]["backend_port"]))
            process.setProcessEnvironment(env)
        log = self._log_widget(card, service_name, port)
        status = QLabel("启动中")
        status.setObjectName("muted")
        service = Service(process, log, status, port)
        self.logs[key] = service
        process.readyReadStandardOutput.connect(lambda s=service, a=app_id, n=service_name: self._read_output(a, n, s))
        process.started.connect(lambda a=app_id, n=service_name: self._append_log(a, n, f"进程已启动，端口 {port}\n"))
        process.errorOccurred.connect(lambda error, a=app_id, n=service_name: self._process_error(a, n, error))
        process.finished.connect(lambda code, status_code, a=app_id, n=service_name: self._process_finished(a, n, code, status_code))
        process.start()
        QTimer.singleShot(900, lambda a=app_id, n=service_name, p=port: self._check_ready(a, n, p))

    def _log_widget(self, card: AppCard, name: str, port: int) -> QPlainTextEdit:
        existing = card.tabs.findChild(QWidget, f"tab_{name}")
        if existing:
            return existing.findChild(QPlainTextEdit)
        tab = QWidget()
        tab.setObjectName(f"tab_{name}")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 4, 0, 0)
        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setMaximumBlockCount(3000)
        log.setPlaceholderText("服务日志会显示在这里…")
        layout.addWidget(log)
        card.tabs.addTab(tab, f"{name}  ·  {port}")
        return log

    def _read_output(self, app_id: str, service_name: str, service: Service) -> None:
        output = bytes(service.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if output:
            service.log.moveCursor(service.log.textCursor().MoveOperation.End)
            service.log.insertPlainText(output)
            service.log.moveCursor(service.log.textCursor().MoveOperation.End)

    def _append_log(self, app_id: str, service_name: str, message: str) -> None:
        service = self.logs.get((app_id, service_name))
        if service:
            service.log.appendPlainText(message.rstrip())

    def _process_error(self, app_id: str, service_name: str, error: QProcess.ProcessError) -> None:
        self._append_log(app_id, service_name, f"进程错误：{error.name}")
        self.cards[app_id].set_running(False, "启动失败")

    def _process_finished(self, app_id: str, service_name: str, code: int, status: QProcess.ExitStatus) -> None:
        label = "正常退出" if code == 0 else f"进程退出，代码 {code}"
        self._append_log(app_id, service_name, label)
        config = next(item for item in self.configs if item["id"] == app_id)
        self._request_status_scan()

    def _check_ready(self, app_id: str, service_name: str, port: int) -> None:
        service = self.logs.get((app_id, service_name))
        if not service or service.process.state() == QProcess.NotRunning:
            return
        if not self.port_states.get((app_id, service_name), False):
            if service.process.state() == QProcess.Running:
                QTimer.singleShot(800, lambda a=app_id, n=service_name, p=port: self._check_ready(a, n, p))
            return
        self._append_log(app_id, service_name, "端口已就绪")
        config = next(item for item in self.configs if item["id"] == app_id)
        if service_name == "frontend" and "frontend" in config:
            self.open_app(app_id)
        self._request_status_scan()

    def _request_status_scan(self) -> None:
        if self.scan_in_progress:
            return
        ports = {
            (config["id"], service_name): self._port_for(config, service_name)
            for config in self.configs
            for service_name in ("backend", "frontend")
            if service_name in config
        }
        self.scan_in_progress = True
        self.scan_task = PortScanTask(ports)
        self.scan_task.signals.completed.connect(self._apply_statuses)
        QThreadPool.globalInstance().start(self.scan_task)

    def _apply_statuses(self, results: dict[tuple[str, str], bool]) -> None:
        self.port_states = results
        self.scan_in_progress = False
        self.scan_task = None
        for config in self.configs:
            app_id = config["id"]
            card = self.cards[app_id]
            states: dict[str, tuple[bool, bool]] = {}
            for service_name in ("backend", "frontend"):
                if service_name not in config:
                    continue
                port = self._port_for(config, service_name)
                service = self.logs.get((app_id, service_name))
                managed_running = bool(service and service.process.state() != QProcess.NotRunning)
                listening = self.port_states.get((app_id, service_name), False)
                external_running = listening and not managed_running
                states[service_name] = (listening, managed_running)
                if listening and external_running:
                    card.set_service_status(service_name, f"运行中 · 外部服务 · {port}", True)
                elif listening:
                    card.set_service_status(service_name, f"运行中 · {port}", True)
                elif managed_running:
                    card.set_service_status(service_name, f"启动中 · {port}", False)
                else:
                    card.set_service_status(service_name, f"已停止 · {port}", False)

            active = [listening or managed for listening, managed in states.values()]
            any_active = any(active)
            all_active = bool(active) and all(active)
            owned = any(managed for _, managed in states.values())
            frontend_ready = states.get("frontend", (False, False))[0]
            if all_active:
                message = "运行中" if owned else "运行中 · 外部服务"
            elif any_active:
                message = "部分运行"
            else:
                message = "已停止"
            card.set_running(
                any_active,
                message,
                can_stop=owned,
                frontend_ready=frontend_ready,
                can_start=not all_active,
            )

    def open_app(self, app_id: str) -> None:
        config = next(item for item in self.configs if item["id"] == app_id)
        if "frontend" not in config:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        url = config["url"].format(frontend_port=config["frontend_port"], backend_port=config.get("backend_port", ""))
        QDesktopServices.openUrl(QUrl(url))

    def stop_app(self, app_id: str) -> None:
        for (current_id, service_name), service in list(self.logs.items()):
            if current_id != app_id or service.process.state() == QProcess.NotRunning:
                continue
            self._stop_process_tree(service.process)
        self._request_status_scan()

    def closeEvent(self, event) -> None:
        active = [service for service in self.logs.values() if service.process.state() != QProcess.NotRunning]
        if active:
            reply = QMessageBox.question(self, "退出", "退出时停止所有由管理器启动的服务吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                for service in active:
                    self._stop_process_tree(service.process)
            else:
                event.ignore()
                return
        event.accept()

    @staticmethod
    def _stop_process_tree(process: QProcess) -> None:
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = AppManager()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
