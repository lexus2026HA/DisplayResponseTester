from time import perf_counter_ns

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

from app.software_tests.motion import Motion

SQUARE_COLORS = ("#ffffff", "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#00ffff", "#ff00ff")

def reflected_position(distance, span):
    if span <= 0:
        return 0
    offset = distance % (2 * span)
    return min(offset, 2 * span - offset)

class SoftwareLatency(Motion):
    def __init__(self, options):
        super().__init__(dict(options, background="#000000"))
        self.color_index = 0
        self.speed = options["speed"]
        self.distance_at_change = 0
        self.speed_changed_at = 0

    def distance(self, seconds):
        return self.distance_at_change + (seconds - self.speed_changed_at) * self.speed

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = 1 if key == Qt.Key.Key_Right else -1
            self.color_index = (self.color_index + step) % len(SQUARE_COLORS)
            self.update()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            seconds = (perf_counter_ns() - self.start) / 1e9
            self.distance_at_change = self.distance(seconds)
            self.speed_changed_at = seconds
            next_speed = round(self.speed * 1.25 if key == Qt.Key.Key_Up else self.speed / 1.25)
            self.speed = max(10, min(12000, next_speed))
            self.update()
        else:
            super().keyPressEvent(event)

    def statistics(self, intervals):
        stats = super().statistics(intervals)
        if stats:
            stats.update(speed_px_s=self.speed, square_color=SQUARE_COLORS[self.color_index],
                         scope="Интервал между началами отрисовок Qt")
        return stats

    def draw_motion(self, painter, seconds):
        ratio = self.devicePixelRatioF()
        side = max(1, min(self.options["size"] / ratio, self.width(), self.height()))
        width, height = self.width() - side, self.height() - side
        distance = self.distance(seconds) / ratio
        horizontal = -.8 if self.options["direction"] == "←" else .8
        x = reflected_position(width/2 + horizontal * distance, width)
        y = reflected_position(height/2 + .6 * distance, height)
        painter.fillRect(QRectF(round(x*ratio)/ratio, round(y*ratio)/ratio, side, side),
                         QColor(SQUARE_COLORS[self.color_index]))

    def draw_hud(self, painter):
        super().draw_hud(painter)
        box = QRectF(12, 43, min(self.width()-24, 680), 30)
        painter.fillRect(box, QColor(15, 20, 28, 225))
        painter.setPen(QColor("#e0ecff"))
        painter.drawText(box.adjusted(12,0,-8,0), Qt.AlignmentFlag.AlignVCenter,
                         f"{self.speed} px/s   |   ← / → цвет   |   ↑ / ↓ скорость   |   Esc выход")
