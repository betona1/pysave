"""ShotKey 진입점.

PyQt6(Qt6)는 기본으로 Per-Monitor DPI Aware v2 를 적용하므로 멀티모니터/고DPI
환경에서 좌표가 정확하게 잡힌다. (수동 ctypes DPI 설정은 Qt 와 충돌하므로 두지 않음)
"""
from __future__ import annotations

import sys


def main() -> int:
    from PyQt6.QtWidgets import QApplication
    from ui.main_window import MainWindow 

    app = QApplication(sys.argv)
    app.setApplicationName("ShotKey")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
