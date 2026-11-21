from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

class Fullscreen(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def launch(self, screen, fullscreen=True):
        self.winId()
        self.windowHandle().setScreen(screen)
        bounds = screen.geometry()
        if fullscreen:
            self.setGeometry(bounds)
            self.showFullScreen()
        else:
            self.resize(min(1000, bounds.width()), min(640, bounds.height()))
            self.move(bounds.center() - self.rect().center())
            self.show()
        screen.destroyed.connect(self.close)
        self.activateWindow()
        self.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
