from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter

from app.gui.fullscreen import Fullscreen

def scan(folder):
    return sorted((path for path in Path(folder).iterdir() if path.is_file() and
                   path.suffix.lower() in {".jpg", ".jpeg", ".png"}),
                  key=lambda path: (path.name.casefold(), path.name))

class Slideshow(Fullscreen):
    changed = Signal(int, bool, int)

    def __init__(self, files, interval, fit, overlay):
        super().__init__()
        self.files = files
        self.fit = fit
        self.overlay = overlay
        self.index = 0
        self.interval = max(1, min(5, interval))
        self.playing = True
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(lambda: self.step(1))
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.load()

    def load(self):
        reader = QImageReader(str(self.files[self.index]))
        reader.setAutoTransform(True)
        self.image = reader.read()
        self.error = reader.errorString() if self.image.isNull() else ""
        self.restart()

    def restart(self):
        self.timer.stop()
        if self.playing:
            self.timer.start(self.interval * 1000)
        self.changed.emit(self.interval, self.playing, self.index)
        self.update()

    def step(self, delta):
        self.index = (self.index + delta) % len(self.files)
        self.load()

    def adjust(self, delta):
        self.interval = max(1, min(5, self.interval + delta))
        self.restart()

    def toggle(self):
        self.playing = not self.playing
        self.restart()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Up):
            self.adjust(1)
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Down):
            self.adjust(-1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.step(1 if key == Qt.Key.Key_Right else -1)
        elif key == Qt.Key.Key_Space:
            self.toggle()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.fillRect(self.rect(), Qt.GlobalColor.black)
            if not self.image.isNull():
                scale = (min if self.fit == "Fit" else max)(
                    self.width() / self.image.width(), self.height() / self.image.height())
                w, h = self.image.width() * scale, self.image.height() * scale
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.drawImage(QRectF((self.width()-w)/2, (self.height()-h)/2, w, h), self.image)
            if self.error:
                p.setPen(Qt.GlobalColor.white)
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.error)
            if self.overlay:
                text = f"{self.files[self.index].name}  •  {self.index+1}/{len(self.files)}  •  {self.interval} с"
                box = QRectF(16, 16, min(self.width()-32, p.fontMetrics().horizontalAdvance(text)+24), 32)
                p.fillRect(box, QColor(0, 0, 0, 190))
                p.setPen(Qt.GlobalColor.white)
                p.drawText(box.adjusted(12, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(box.width()-12)))
