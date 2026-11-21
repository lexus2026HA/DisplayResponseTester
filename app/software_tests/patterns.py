import random

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient

from app.display_info.model import GRAY_LEVELS
from app.gui.fullscreen import Fullscreen

COLORS = ("#ff0000", "#00ff00", "#0000ff", "#ffff00", "#00ffff", "#ff00ff", "#ffffff", "#000000")
TRANSITION_MODES = ("Gray-to-Gray Patterns", "Black/White Transitions", "Color Transitions")
GRAY_PATTERNS = ("Ступени и градиент", "Серые кольца", "Ступени разной плотности",
                 "Встречные шкалы", "Тени и света", "Радиальные шкалы",
                 "Переход между выбранными уровнями")

def gray(level):
    return QColor(level, level, level)

def ramp(painter, box, reverse=False):
    gradient = QLinearGradient(box.topLeft(), box.topRight())
    gradient.setColorAt(0, gray(255 if reverse else 0))
    gradient.setColorAt(1, gray(0 if reverse else 255))
    painter.fillRect(box, gradient)

def steps(painter, box, values, labels=False):
    for index, level in enumerate(values):
        x1 = round(box.left() + index*box.width()/len(values))
        x2 = round(box.left() + (index+1)*box.width()/len(values))
        cell = QRectF(x1, box.top(), x2-x1, box.height())
        painter.fillRect(cell, gray(level))
        if labels:
            painter.setPen(gray(255 if level < 115 else 0))
            painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(level))

def rings(width, height):
    w, h = max(2, width), max(2, height)
    y, x = np.ogrid[:h, :w]
    radius = np.hypot(x-w*.5, y-h*.5) / min(w,h)
    wave = np.cos(2*np.pi*(13*radius + 125*radius**2))
    envelope = np.exp(-5*radius**2)
    values = np.ascontiguousarray(np.rint(127.5+127.5*wave*envelope).astype(np.uint8))
    return QImage(values.data, w, h, values.strides[0], QImage.Format.Format_Grayscale8).copy()

class Transitions(Fullscreen):
    def __init__(self, options):
        super().__init__()
        self.mode = options["motion"]
        self.options = options
        self.frames = COLORS if self.mode == "Color Transitions" else (
            ("#000000", "#ffffff") if self.mode == "Black/White Transitions" else GRAY_PATTERNS)
        self.index = 0
        self.show_help = False
        self.gray_phase = 0
        self.cached_rings = QImage()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(round(1000 * options["hold"]))
        self.timer.timeout.connect(self.advance)
        self.gray_timer = QTimer(self)
        self.gray_timer.setInterval(self.timer.interval())
        self.gray_timer.timeout.connect(self.flip_gray)
        if self.mode == "Black/White Transitions":
            self.timer.start()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def flip_gray(self):
        self.gray_phase ^= 1
        self.update()

    def advance(self, direction=1):
        self.index = (self.index + direction) % len(self.frames)
        self.gray_phase = 0
        self.gray_timer.stop()
        if self.mode == "Gray-to-Gray Patterns" and self.index == len(self.frames)-1 and not self.timer.isActive():
            self.gray_timer.start()
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                if self.timer.isActive():
                    self.timer.stop()
                    if self.frames == GRAY_PATTERNS and self.index == len(self.frames)-1:
                        self.gray_timer.start()
                else:
                    self.gray_timer.stop()
                    self.timer.start()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.advance(-1 if key in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1)
            if self.timer.isActive():
                self.timer.start()
        elif key == Qt.Key.Key_H:
            self.show_help = not self.show_help
            self.update()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        self.gray_timer.stop()
        super().closeEvent(event)

    def paintEvent(self, event):
        with QPainter(self) as p:
            if self.mode == "Gray-to-Gray Patterns":
                self.draw_gray(p)
            else:
                p.fillRect(self.rect(), QColor(self.frames[self.index]))
            if self.show_help:
                box = QRectF(12, 12, min(560, self.width()-24), 37)
                p.fillRect(box, QColor(20,20,20,230))
                p.setPen(gray(245))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter,
                           f"{self.index+1}/{len(self.frames)}   {self.frames[self.index]}   •   Space / ← → / H / Esc")

    def draw_gray(self, painter):
        w, h = self.width(), self.height()
        painter.fillRect(self.rect(), gray(0))
        if self.index == 0:
            steps(painter, QRectF(0,0,w,h*.5), [round(i*255/31) for i in range(31,-1,-1)])
            ramp(painter, QRectF(0,h*.5,w,h*.5))
        elif self.index == 1:
            ratio = self.devicePixelRatioF()
            pixel_size = (round(w*ratio), round(h*ratio))
            if (self.cached_rings.width(), self.cached_rings.height()) != pixel_size:
                self.cached_rings = rings(*pixel_size)
            painter.drawImage(QRectF(0,0,w,h), self.cached_rings)
        elif self.index == 2:
            for i, count in enumerate((9, 13, 18, 24)):
                values = [round(255*j/(count-1)) for j in range(count)]
                steps(painter, QRectF(0,(i+.12)*h/5,w,h*.16), values, True)
            ramp(painter, QRectF(0,h*.82,w,h*.18))
        elif self.index == 3:
            steps(painter, QRectF(0,0,w,h*.5), tuple(reversed(GRAY_LEVELS)), True)
            steps(painter, QRectF(0,h*.5,w,h*.5), GRAY_LEVELS, True)
        elif self.index == 4:
            steps(painter, QRectF(0,0,w,h*.5), range(0,17,2), True)
            steps(painter, QRectF(0,h*.5,w,h*.5), range(239,256,2), True)
        elif self.index == 5:
            for index, stepped in enumerate((False, True)):
                box = QRectF(index*w/2,0,w/2,h)
                radius = min(box.width(), box.height())*.46
                gradient = QRadialGradient(box.center(), radius)
                if stepped:
                    for i in range(9):
                        level = GRAY_LEVELS[8-i]
                        gradient.setColorAt(i/9, gray(level))
                        gradient.setColorAt((i+1)/9-.0001, gray(level))
                    gradient.setColorAt(1, gray(0))
                else:
                    gradient.setColorAt(0, gray(255))
                    gradient.setColorAt(1, gray(0))
                painter.fillRect(box, gradient)
        else:
            a, b = self.options["gray_from"], self.options["gray_to"]
            painter.fillRect(self.rect(), gray(a))
            painter.fillRect(QRectF(w*.2,h*.2,w*.6,h*.6), gray((a,b)[self.gray_phase]))

def dimming_layout(previous_count=0, rng=random):
    counts = [value for value in range(12, 49) if value != previous_count]
    indices = rng.sample(range(96), rng.choice(counts))
    return [(index % 12, index // 12, rng.choice((0, 3, 7, 11)),
             rng.uniform(.35,.86)) for index in indices]
