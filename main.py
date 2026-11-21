import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.utils.settings import ROOT, Settings

def main():
    parser = argparse.ArgumentParser(description="Display Response Tester V1.2")
    parser.add_argument("--smoke", action="store_true", help="launch the application and close after initialization")
    args = parser.parse_args()
    directory = ROOT / "logs"
    directory.mkdir(exist_ok=True)
    handler = RotatingFileHandler(directory / "display-response.log", maxBytes=1_000_000,
                                  backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Display Response Tester")
    app.setApplicationVersion("1.2")
    app.setStyle("Fusion")
    window = MainWindow(Settings())
    window.show()
    if args.smoke:
        def check():
            if window.refreshing:
                QTimer.singleShot(50, check)
                return
            logging.info("Startup smoke: %d screens; %d slideshow images",
                         window.display_combo.count(), len(window.files))
            app.exit(0 if window.display_combo.count() else 1)
        QTimer.singleShot(150, check)
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
