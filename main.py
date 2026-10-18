from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from denny_app_manager.config import load_apps, load_local_settings
from denny_app_manager.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow(load_apps(), load_local_settings())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
