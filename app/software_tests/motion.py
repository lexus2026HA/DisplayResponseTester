import math
import statistics
from collections import deque
from time import perf_counter_ns

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtSvg import QSvgRenderer

from app.gui.fullscreen import Fullscreen
from app.software_tests.patterns import dimming_layout, gray
from app.utils.settings import RESOURCES

MODES = ("Pepper", "Cart", "Airplane", "Ghosting", "Inverse Ghosting",
         "Overdrive Artifacts", "Frame Skipping", "Frame Pacing", "Moving Text",
         "Moving Squares", "Moving Squares (Frame Stepped)", "Local Dimming")
SQUARE_MODES = ("Moving Squares", "Moving Squares (Frame Stepped)")
LIVE_TIMING_MODES = (*SQUARE_MODES, "Software Latency")
FOUR_LANES = ("Pepper", "Cart", "Airplane", *SQUARE_MODES)
LANE_RATIOS = (2.0, 1.5, 1.0, .5)
SPRITES = {"Pepper": "pepper.svg", "Cart": "cart.svg", "Airplane": "airplane.svg"}

def frame_stats(intervals):
    if not intervals:
        return {}
    avg = statistics.mean(intervals)
    return {"fps": round(1000 / avg, 2), "mean_ms": round(avg, 3),
            "jitter_ms": round(statistics.pstdev(intervals), 3),
            "p95_ms": round(sorted(intervals)[math.ceil(len(intervals)*.95)-1], 3),
            "max_ms": round(max(intervals), 3), "samples": len(intervals)}

class Motion(Fullscreen):
    stats_ready = Signal(dict)

    def __init__(self, options):
        super().__init__()
        self.options = options
        self.mode = options["motion"]
        self.sprite = QSvgRenderer(str(RESOURCES / "assets" / SPRITES[self.mode]), self) if self.mode in SPRITES else None
        self.start = perf_counter_ns()
        self.last_paint = None
        self.last_stats = 0
        self.live_stats = {}
        self.queued_ns = None
        self.queue_times = deque(maxlen=600)
        self.frame_index = 0
        self.dimming = dimming_layout() if self.mode == "Local Dimming" else []
        self.recent = deque(maxlen=600)
        self.all_intervals = deque(maxlen=60000)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def tick(self):
        if self.queued_ns is None:
            self.queued_ns = perf_counter_ns()
        self.update()
        elapsed = perf_counter_ns() - self.start
        fps = self.options["fps"]
        step = elapsed * fps // 1_000_000_000 + 1
        deadline = step * 1_000_000_000 // fps
        self.timer.start(max(1, math.ceil((deadline-elapsed)/1_000_000)))

    def closeEvent(self, event):
        self.timer.stop()
        self.stats_ready.emit(self.statistics(self.all_intervals))
        super().closeEvent(event)

    def statistics(self, intervals):
        stats = frame_stats(intervals)
        if stats and self.mode in LIVE_TIMING_MODES and self.queue_times:
            stats["request_to_paint_ms"] = round(statistics.mean(self.queue_times), 3)
            stats["request_samples"] = len(self.queue_times)
        return stats

    def keyPressEvent(self, event):
        if self.mode == "Local Dimming" and event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self.dimming = dimming_layout(len(self.dimming))
                self.update()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        now = perf_counter_ns()
        if self.queued_ns is not None:
            self.queue_times.append((now-self.queued_ns)/1e6)
            self.queued_ns = None
        if self.last_paint is not None:
            delta = (now - self.last_paint) / 1e6
            if delta > 0:
                self.recent.append(delta)
                self.all_intervals.append(delta)
        self.last_paint = now
        live_timing = self.mode in LIVE_TIMING_MODES
        refresh_ns = 250_000_000 if live_timing else 500_000_000
        if now - self.last_stats >= refresh_ns:
            self.live_stats = self.statistics(self.recent)
            self.stats_ready.emit(self.live_stats)
            if live_timing:
                self.recent.clear()
            self.last_stats = now
        t = (now - self.start) / 1e9
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor(self.options["background"]))
            if self.mode in ("Frame Skipping", "Frame Pacing"):
                self.draw_timing(painter, t)
            elif self.mode == "Local Dimming":
                self.draw_dimming(painter, t)
            else:
                motion_time = self.frame_index / self.options["fps"] if self.mode == SQUARE_MODES[1] else t
                self.draw_motion(painter, motion_time)
                if live_timing:
                    self.draw_hud(painter)
        self.frame_index += 1

    def draw_timing(self, painter, t):
        cols, rows = 12, 6
        step = int(t * self.options["fps"]) % (cols * rows)
        if self.mode == "Frame Pacing":
            painter.fillRect(QRectF(0, self.height()*.3, self.width(), self.height()*.4), gray(20))
            x = (t * self.options["speed"] / self.devicePixelRatioF()) % self.width()
            painter.fillRect(QRectF(x, self.height()*.3, 12, self.height()*.4), gray(255))
            return
        w, h = self.width()/cols, self.height()/rows
        painter.fillRect(self.rect(), gray(8))
        for i in range(cols * rows):
            cell = QRectF(i%cols*w + 4, i//cols*h + 4, w-8, h-8)
            painter.fillRect(cell, gray(255 if i == step else 25))

    def draw_dimming(self, painter, t):
        painter.fillRect(self.rect(), gray(19))
        dx, dy = self.width()/12, self.height()/8
        for col, row, level, factor in self.dimming:
            size = min(dx, dy)*factor
            painter.fillRect(QRectF((col+.5)*dx-size/2, (row+.5)*dy-size/2, size, size), gray(level))
        size = min(self.width(), self.height())*.065
        x = (t*self.options["speed"]/self.devicePixelRatioF()) % (self.width()+size)-size
        y = self.height()*(.42+.30*math.sin(t*.9))
        painter.fillRect(QRectF(x,y,size,size), gray(255))

    def draw_hud(self, painter):
        stats = self.live_stats
        label = "Ожидание кадров…"
        if stats:
            delay = stats.get("request_to_paint_ms")
            timing = f"   |   Запрос → Qt: {delay:.2f} мс" if delay is not None else ""
            label = (f"{stats['fps']:.1f} FPS   |   Кадр: {stats['mean_ms']:.2f} мс"
                     f"   |   P95: {stats['p95_ms']:.2f} мс{timing}")
        box = QRectF(12, 9, min(self.width()-24, 680), 33)
        painter.fillRect(box, QColor(15, 20, 28, 225))
        painter.setPen(gray(245))
        painter.drawText(box.adjusted(12,0,-8,0), Qt.AlignmentFlag.AlignVCenter, label)

    def draw_motion(self, painter, t):
        opts = self.options
        ghost = self.mode in ("Ghosting", "Inverse Ghosting", "Overdrive Artifacts")
        fixed = self.mode in FOUR_LANES
        lanes = 4 if fixed else 3 if ghost else opts["lanes"]
        size = min(opts["size"] / self.devicePixelRatioF(), self.height()/lanes*.85)
        for lane in range(lanes):
            multiplier = LANE_RATIOS[lane] if fixed else 1 + lane*.5
            speed = opts["speed"] * multiplier / self.devicePixelRatioF()
            lane_h = self.height() / lanes
            y = (lane + .5)*lane_h
            if ghost:
                backgrounds = (32, 96, 160) if self.mode == "Overdrive Artifacts" else (48, 112, 176)
                painter.fillRect(QRectF(0,lane*lane_h,self.width(),lane_h), gray(backgrounds[lane]))
            for j in range(opts["count"]):
                span = self.width()+size*2
                x = (t*speed+j*span/opts["count"])%span-size
                if opts["direction"] == "←":
                    x = self.width()-x
                painter.save()
                painter.translate(x, y)
                if opts["direction"] == "←" and self.sprite:
                    painter.scale(-1, 1)
                if self.sprite:
                    self.draw_sprite(painter, size, speed, t)
                elif self.mode == "Moving Text":
                    painter.setFont(QFont("Consolas", max(8, int(size/5)), 600))
                    painter.setPen(Qt.GlobalColor.white if QColor(opts["background"]).lightness() < 140 else Qt.GlobalColor.black)
                    painter.drawText(QRectF(-size, -size*.5, size*2,size), Qt.AlignmentFlag.AlignCenter, "Display  012345")
                elif self.mode in SQUARE_MODES:
                    level = 238 if QColor(opts["background"]).lightness() < 145 else 18
                    painter.fillRect(QRectF(-size*.5,-size*.5,size,size), gray(level))
                else:
                    level = (232, 168, 224)[lane] if ghost and self.mode == "Ghosting" else (15, 210, 80)[lane]
                    painter.fillRect(QRectF(-size*.5,-size*.25,size,size*.5), gray(level))
                    if ghost and self.mode == "Overdrive Artifacts":
                        painter.fillRect(QRectF(-size*.5,-size*.25,size*.5,size*.5), gray((190, 30, 235)[lane]))
                painter.restore()

    def draw_sprite(self, painter, size, speed, t):
        painter.save()
        painter.scale(size/120, size/120)
        painter.translate(-60, -40)
        self.sprite.render(painter, QRectF(0, 0, 120, 80))
        if self.mode == "Cart":
            rpm = self.options["rpm"]
            degrees = t*rpm*6 if rpm else math.degrees(t*speed/(size*10/120))
            for x in (44, 91):
                painter.save()
                painter.translate(x, 64)
                painter.rotate(degrees)
                painter.setPen(gray(20))
                painter.setBrush(gray(45))
                painter.drawEllipse(QPointF(), 10, 10)
                painter.setPen(gray(205))
                for angle in range(0, 360, 60):
                    rad = math.radians(angle)
                    painter.drawLine(QPointF(), QPointF(8*math.cos(rad), 8*math.sin(rad)))
                painter.restore()
        elif self.mode == "Airplane":
            painter.translate(107, 50)
            painter.rotate(t*self.options["rpm"]*6)
            painter.setPen(gray(25))
            painter.setBrush(QColor("#c6dbea"))
            painter.drawEllipse(QRectF(-3, -23, 6, 46))
            painter.setBrush(QColor("#eb4a42"))
            painter.drawEllipse(QPointF(), 4, 4)
        painter.restore()
