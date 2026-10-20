from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QThreadPool, QTimer, Signal

from denny_app_manager.config import PROJECTS_ROOT
from denny_app_manager.services.ports import PortScanTask
from denny_app_manager.services.processes import (
    ManagedService,
    append_process_output,
    build_service_command,
    new_log_decoder,
    stop_process_tree,
)


class ServiceController(QObject):
    status_updated = Signal(str, dict)
    log_received = Signal(str, str, str)
    open_requested = Signal(str)

    def __init__(self, configs: list[dict], parent: QObject | None = None):
        super().__init__(parent)
        self.configs = configs
        self.services: dict[tuple[str, str], ManagedService] = {}
        self.port_states: dict[tuple[str, str], bool] = {}
        self.scan_in_progress = False
        self.scan_requested = False
        self.scan_task: PortScanTask | None = None
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(2000)
        self.monitor_timer.timeout.connect(self.request_status_scan)

    def start_monitoring(self) -> None:
        self.monitor_timer.start()
        self.request_status_scan()

    def _port_for(self, config: dict, service_name: str) -> int:
        return int(config[f"{service_name}_port"])

    def start_app(self, app_id: str) -> None:
        config = self._config(app_id)
        for service_name in ("backend", "frontend"):
            if service_name not in config:
                continue
            managed = self.services.get((app_id, service_name))
            port = self._port_for(config, service_name)
            if managed and managed.process.state() != QProcess.NotRunning:
                continue
            if self.port_states.get((app_id, service_name), False):
                self.log_received.emit(app_id, service_name, f"端口 {port} 已有服务监听，将监控现有服务。\n")

        for index, service_name in enumerate(("backend", "frontend")):
            if service_name not in config:
                continue
            managed = self.services.get((app_id, service_name))
            if (managed and managed.process.state() != QProcess.NotRunning) or self.port_states.get((app_id, service_name), False):
                continue
            QTimer.singleShot(index * 800, lambda n=service_name: self._start_service(config, n))

        if "frontend" in config and self.port_states.get((app_id, "frontend"), False):
            self.open_requested.emit(app_id)
        self._emit_all_statuses()

    def _start_service(self, config: dict, service_name: str) -> None:
        app_id = config["id"]
        port = self._port_for(config, service_name)
        key = (app_id, service_name)
        existing = self.services.get(key)
        if existing and existing.process.state() != QProcess.NotRunning:
            return
        command, arguments, cwd = build_service_command(
            PROJECTS_ROOT / config["project"], config[service_name], config, service_name, port
        )
        if not cwd.is_dir():
            self.log_received.emit(app_id, service_name, f"工作目录不存在：{cwd}\n")
            self.request_status_scan()
            return

        process = QProcess(self)
        process.setWorkingDirectory(str(cwd))
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.setProgram(command)
        process.setArguments(arguments)
        env = QProcessEnvironment.systemEnvironment()
        if service_name == "frontend":
            env.insert("PORT", str(port))
        env.insert(
            "DENNY_BACKEND_PORT",
            str(config[service_name].get("backend_port", config.get("backend_port", ""))),
        )
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("NO_COLOR", "1")
        process.setProcessEnvironment(env)

        service = ManagedService(process, port, new_log_decoder())
        self.services[key] = service
        process.readyReadStandardOutput.connect(lambda s=service, a=app_id, n=service_name: self._read_output(a, n, s))
        process.started.connect(lambda a=app_id, n=service_name, p=port: self.log_received.emit(a, n, f"进程已启动，端口 {p}\n"))
        process.errorOccurred.connect(lambda error, a=app_id, n=service_name: self._process_error(a, n, error))
        process.finished.connect(lambda code, status, a=app_id, n=service_name: self._process_finished(a, n, code))
        process.start()
        self._emit_app_status(app_id)
        QTimer.singleShot(900, lambda a=app_id, n=service_name, p=port: self._check_ready(a, n, p))

    def _read_output(self, app_id: str, service_name: str, service: ManagedService, *, final: bool = False) -> None:
        raw = bytes(service.process.readAllStandardOutput())
        output = service.decoder.decode(raw, final=final)
        if output:
            self.log_received.emit(app_id, service_name, output)

    def _process_error(self, app_id: str, service_name: str, error: QProcess.ProcessError) -> None:
        self.log_received.emit(app_id, service_name, f"进程错误：{error.name}\n")
        self._emit_app_status(app_id)

    def _process_finished(self, app_id: str, service_name: str, code: int) -> None:
        service = self.services.get((app_id, service_name))
        if service:
            self._read_output(app_id, service_name, service, final=True)
        label = "正常退出" if code == 0 else f"进程退出，代码 {code}"
        self.log_received.emit(app_id, service_name, label + "\n")
        self.request_status_scan()

    def _check_ready(self, app_id: str, service_name: str, port: int) -> None:
        service = self.services.get((app_id, service_name))
        if not service or service.process.state() == QProcess.NotRunning:
            return
        if not self.port_states.get((app_id, service_name), False):
            if service.process.state() == QProcess.Running:
                QTimer.singleShot(800, lambda a=app_id, n=service_name, p=port: self._check_ready(a, n, p))
            return
        self.log_received.emit(app_id, service_name, "端口已就绪\n")
        if service_name == "frontend":
            self.open_requested.emit(app_id)
        self.request_status_scan()

    def request_status_scan(self) -> None:
        if self.scan_in_progress:
            self.scan_requested = True
            return
        ports = {
            (config["id"], name): self._port_for(config, name)
            for config in self.configs
            for name in ("backend", "frontend")
            if name in config
        }
        self.scan_in_progress = True
        self.scan_task = PortScanTask(ports)
        self.scan_task.signals.completed.connect(self._on_ports_scanned)
        QThreadPool.globalInstance().start(self.scan_task)

    def _on_ports_scanned(self, results: dict[tuple[str, str], bool]) -> None:
        self.port_states = results
        self.scan_in_progress = False
        self.scan_task = None
        self._emit_all_statuses()
        if self.scan_requested:
            self.scan_requested = False
            QTimer.singleShot(100, self.request_status_scan)

    def _emit_all_statuses(self) -> None:
        for config in self.configs:
            self._emit_app_status(config["id"])

    def _emit_app_status(self, app_id: str) -> None:
        config = self._config(app_id)
        services = {}
        for name in ("backend", "frontend"):
            if name not in config:
                continue
            key = (app_id, name)
            port = self._port_for(config, name)
            managed = self.services.get(key)
            managed_running = bool(managed and managed.process.state() != QProcess.NotRunning)
            listening = self.port_states.get(key, False)
            if listening:
                text = f"运行中 · {port}" + (" · 外部服务" if not managed_running else "")
            elif managed_running:
                text = f"启动中 · {port}"
            else:
                text = f"已停止 · {port}"
            services[name] = {
                "port": port,
                "listening": listening,
                "managed": managed_running,
                "text": text,
            }
        active = [state["listening"] or state["managed"] for state in services.values()]
        any_active = any(active)
        all_active = bool(active) and all(active)
        owned = any(state["managed"] for state in services.values())
        message = "运行中" if all_active and owned else (
            "运行中 · 外部服务" if all_active else "部分运行" if any_active else "已停止"
        )
        self.status_updated.emit(app_id, {
            "services": services,
            "running": any_active,
            "message": message,
            "can_stop": owned,
            "can_start": not all_active,
            "frontend_ready": services.get("frontend", {}).get("listening", False),
        })

    def stop_app(self, app_id: str) -> None:
        self.status_updated.emit(app_id, {"stopping": True, "message": "正在停止…"})
        for (current_id, _), service in list(self.services.items()):
            if current_id == app_id:
                stop_process_tree(service.process)
        QTimer.singleShot(350, self.request_status_scan)
        self.request_status_scan()

    def has_active_processes(self) -> bool:
        return any(service.process.state() != QProcess.NotRunning for service in self.services.values())

    def stop_all(self) -> None:
        for service in self.services.values():
            stop_process_tree(service.process)

    def _config(self, app_id: str) -> dict:
        return next(config for config in self.configs if config["id"] == app_id)
