from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from denny_app_manager.controllers.git_controller import GitController
from denny_app_manager.controllers.service_controller import ServiceController
from denny_app_manager.config import PROJECTS_ROOT
from denny_app_manager.services.editor import open_project_in_vscode
from denny_app_manager.ui.app_card import AppCard


class MainWindow(QMainWindow):
    def __init__(self, configs: list[dict], local_settings: dict[str, str] | None = None):
        super().__init__()
        self.configs = configs
        self.local_settings = local_settings or {}
        self.cards: dict[str, AppCard] = {}
        self.setWindowTitle("Denny App Manager")
        self.resize(1050, 850)
        self._build_ui()
        self.services = ServiceController(configs, self)
        self.git = GitController(configs, self)
        self._connect_controllers()
        self.services.start_monitoring()
        self.git.start_monitoring()

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(24, 22, 24, 22)
        root_layout.setSpacing(16)
        heading = QLabel("Denny App Manager")
        heading.setObjectName("pageTitle")
        subtitle = QLabel("本地服务控制台 · 独立端口 · 实时日志")
        subtitle.setObjectName("muted")
        info = QLabel("服务只监听本机。点击启动会运行项目的前后端，并在就绪后打开页面。")
        info.setObjectName("info")
        root_layout.addWidget(heading)
        root_layout.addWidget(subtitle)
        root_layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        list_widget = QWidget()
        cards_layout = QVBoxLayout(list_widget)
        cards_layout.setContentsMargins(2, 2, 10, 2)
        cards_layout.setSpacing(14)
        for config in self.configs:
            card = AppCard(config)
            card.start_requested.connect(self._start_app)
            card.stop_requested.connect(self._stop_app)
            card.open_requested.connect(self._open_app)
            card.open_project_requested.connect(self._open_project)
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
            #pushReady { background: #16875b; border: 1px solid #25b77d; color: white; font-weight: 700; }
            #pushUnavailable:disabled { background: #202833; color: #667487; }
        """)

    def _connect_controllers(self) -> None:
        self.services.status_updated.connect(self._service_status_updated)
        self.services.log_received.connect(self._service_log_received)
        self.services.open_requested.connect(self._open_app)
        self.git.status_updated.connect(self._git_status_updated)
        self.git.log_received.connect(self._git_log_received)
        for card in self.cards.values():
            card.fetch_rebase_requested.connect(self.git.fetch_rebase)
            card.push_requested.connect(self.git.push)

    def _service_status_updated(self, app_id: str, status: dict) -> None:
        card = self.cards[app_id]
        card.set_runtime_status(status)

    def _service_log_received(self, app_id: str, service_name: str, text: str) -> None:
        self.cards[app_id].append_service_log(service_name, text)

    def _git_status_updated(self, app_id: str, status: dict, busy: bool) -> None:
        self.cards[app_id].set_git_status(status, busy)

    def _git_log_received(self, app_id: str, text: str) -> None:
        self.cards[app_id].append_git_log(text)

    def _start_app(self, app_id: str) -> None:
        self.services.start_app(app_id)

    def _stop_app(self, app_id: str) -> None:
        self.services.stop_app(app_id)

    def _open_app(self, app_id: str) -> None:
        config = next(item for item in self.configs if item["id"] == app_id)
        if "frontend" not in config:
            return
        url = config["url"].format(
            frontend_port=config["frontend_port"],
            backend_port=config.get("backend_port", ""),
        )
        QDesktopServices.openUrl(QUrl(url))

    def _open_project(self, app_id: str) -> None:
        config = next(item for item in self.configs if item["id"] == app_id)
        success, message = open_project_in_vscode(
            PROJECTS_ROOT / config["project"],
            self.local_settings.get("DENNY_VSCODE_PATH"),
        )
        if not success:
            QMessageBox.warning(self, "打开工程失败", message)

    def closeEvent(self, event) -> None:
        if self.services.has_active_processes():
            reply = QMessageBox.question(
                self,
                "退出",
                "退出时停止所有由管理器启动的服务吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.services.stop_all()
            else:
                event.ignore()
                return
        event.accept()
