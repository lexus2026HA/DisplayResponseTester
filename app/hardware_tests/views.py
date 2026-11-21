from time import perf_counter_ns

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from app.gui.fullscreen import Fullscreen
from app.software_tests.patterns import gray

class Patch(Fullscreen):
    finished = Signal(bool, list)

    def __init__(self, a, b, hold, repeats):
        super().__init__()
        self.levels = (a, b)
        self.hold = int(hold * 1e9)
        self.last_index = 2*repeats
        self.start = None
        self.index = -1
        self.events = []
        self.completed = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def tick(self):
        if self.index == self.last_index:
            self.completed = True
            self.close()
            return
        self.update()

    def paintEvent(self, event):
        now = perf_counter_ns()
        if self.start is None:
            self.start = now
        index = min((now-self.start)//self.hold, self.last_index)
        level = self.levels[index % 2]
        with QPainter(self) as painter:
            painter.fillRect(self.rect(), gray(80))
            painter.fillRect(QRectF(self.width()*.2,self.height()*.2,self.width()*.6,self.height()*.6), gray(level))
        if self.index != index:
            self.index = index
            self.events.append({"step": index, "level": level, "paint_start_ns": now,
                                "paint_end_ns": perf_counter_ns()})
        remaining = self.start + (index+1)*self.hold - perf_counter_ns()
        self.timer.start(max(1, (remaining+999999)//1000000))

    def closeEvent(self, event):
        self.timer.stop()
        self.finished.emit(self.completed, self.events)
        super().closeEvent(event)

class Preview(QWidget):
    changed = Signal(list)

    def __init__(self, roi):
        super().__init__()
        self.setMinimumSize(280, 175)
        self.image = QImage()
        self.roi = list(roi)
        self.anchor = self.current = None

    def picture_rect(self):
        if self.image.isNull():
            return QRectF()
        scale = min(self.width()/self.image.width(), self.height()/self.image.height())
        w, h = self.image.width()*scale, self.image.height()*scale
        return QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)

    def normalized(self, p):
        rect = self.picture_rect()
        return QPointF(max(0,min(1,(p.x()-rect.x())/rect.width())),
                       max(0,min(1,(p.y()-rect.y())/rect.height())))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.picture_rect().contains(event.position()):
            self.anchor = self.current = self.normalized(event.position())

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self.current = self.normalized(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        if self.anchor is None:
            return
        rect = QRectF(self.anchor, self.normalized(event.position())).normalized()
        self.anchor = self.current = None
        if rect.width() >= .005 and rect.height() >= .005:
            self.roi = [rect.x(), rect.y(), rect.width(), rect.height()]
            self.changed.emit(self.roi)
        self.update()

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.fillRect(self.rect(), QColor("#151c28"))
            rect = self.picture_rect()
            if rect.isEmpty():
                p.setPen(QColor("#d5dfef"))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Предпросмотр камеры")
                return
            p.drawImage(rect, self.image)
            roi = QRectF(self.anchor, self.current).normalized() if self.anchor is not None else QRectF(*self.roi)
            p.setPen(QPen(QColor("#7af4cf"), 2))
            p.drawRect(QRectF(rect.x()+roi.x()*rect.width(),rect.y()+roi.y()*rect.height(),
                              roi.width()*rect.width(), roi.height()*rect.height()))

def draw_chart(p, rect, samples, simulation):
    p.fillRect(rect, QColor("#151c28"))
    p.setPen(QColor("#e1e9f8"))
    p.drawText(rect.adjusted(12, 6, -12, -6), Qt.AlignmentFlag.AlignTop,
               "Яркость ROI • " + ("SIMULATION" if simulation else "коды камеры"))
    box = rect.adjusted(46, 35, -16, -29)
    if box.isEmpty():
        return
    for v in (0, 64, 128, 192, 255):
        y = box.bottom() - v/255*box.height()
        p.setPen(QColor("#36445c"))
        p.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
        p.setPen(QColor("#bbc9dd"))
        p.drawText(QPointF(box.left()-33, y+4), str(v))
    if len(samples) < 2:
        return
    start = samples[0]["time_ns"]
    duration = (samples[-1]["time_ns"]-start)/1e9
    if duration <= 0:
        return
    for i in range(5):
        frac = i/4
        p.drawText(QPointF(box.left()+frac*box.width()-10,box.bottom()+20),f"{duration*frac:.1f}")
    p.drawText(QPointF(box.right()+4, box.bottom()+20), "с")
    p.setPen(QPen(QColor("#78e6c6"), 1.5))
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.drawPolyline(QPolygonF([QPointF(box.left() + ((s["time_ns"]-start)/1e9/duration)*box.width(),
                                     box.bottom() - s["mean"]/255*box.height()) for s in samples]))

class Chart(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 175)
        self.samples = []
        self.simulation = False

    def paintEvent(self, event):
        with QPainter(self) as p:
            draw_chart(p, QRectF(self.rect()), self.samples, self.simulation)
