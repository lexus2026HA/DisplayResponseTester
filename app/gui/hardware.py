import base64
import time
from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.display_info.model import GRAY_LEVELS
from app.gui.common import button, combo, horizontal, page, spin, start_task
from app.hardware_tests.client import AgentClient, AgentError
from app.hardware_tests.esp_usb import EspUsbClient, ports
from app.hardware_tests.measurement import analyze, simulate
from app.hardware_tests.views import Chart, Patch, Preview

class HardwarePage:
    def __init__(self, settings, screen, display_id, launch, save_result, export):
        self.settings, self.screen, self.launch = settings, screen, launch
        self.save_result = save_result
        self.display_id = display_id
        self.widget, root = page("Камера и оптические переходы",
                                "Orange Pi по Ethernet или Simulation. Выделите ROI мышью внутри тестового участка.")
        self.client = None
        self.cameras = {}
        self.busy = False
        self.session = None
        self.patch = None
        self.events = []
        self.complete = False
        self.started = 0
        self.cancelled = False
        self.rtts = []
        self.options = None
        self.poller = QTimer(self.widget)
        self.poller.setInterval(300)
        self.poller.timeout.connect(self.poll)
        self.host = QLineEdit(settings["host"])
        self.host.setPlaceholderText("IPv4 / IPv6 Orange Pi")
        self.connect_button = button("Подключить", self.connect)
        self.simulation = QCheckBox("Simulation")
        self.simulation.setChecked(settings["simulation"])
        self.simulation.toggled.connect(self.configure)
        horizontal(root, QLabel("Адрес"), self.host, self.connect_button, self.simulation)

        grid = QGridLayout()
        self.controls = {}
        self.device = QComboBox()
        self.device.currentTextChanged.connect(self.mode_details)
        self.resolution = combo([settings["resolution"]], settings["resolution"])
        self.resolution.setEditable(True)
        self.format = combo(dict.fromkeys([settings["camera_format"], "MJPG", "YUYV"]), settings["camera_format"])
        self.format.setEditable(True)
        specs = (
            ("Камера", self.device, "device"),
            ("Разрешение", self.resolution, "resolution"),
            ("FourCC", self.format, "format"),
            ("FPS камеры", spin(1,240,settings["camera_fps"]), "fps"),
            ("Экспозиция¹", spin(0,1000000,settings["exposure"]), "exposure"),
            ("Усиление", spin(0,100000,settings["gain"]), "gain"),
            ("Из", combo(GRAY_LEVELS,settings["gray_from"]), "gray_from"),
            ("В", combo(GRAY_LEVELS,settings["gray_to"]), "gray_to"),
            ("Удержание", spin(.25,10,settings["hold"]," с",True), "hold"),
            ("Циклы", spin(1,12,settings["repeats"]), "repeats"),
        )
        for i, (label, control, key) in enumerate(specs):
            row, col = divmod(i, 5)
            grid.addWidget(QLabel(label), row*2, col)
            grid.addWidget(control, row*2+1, col)
            self.controls[key] = control
        root.addLayout(grid)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.preview_btn = button("Предпросмотр", self.preview)
        self.start_btn = button("Запустить тест", self.start, True)
        self.stop_btn = button("Остановить", self.stop)
        horizontal(root, self.preview_btn, self.start_btn, self.stop_btn, button("Экспорт", export))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.hide()
        self.details.setMaximumHeight(180)
        horizontal(root, button("Режимы и управления камеры", lambda: self.details.setVisible(self.details.isHidden())),
                   QLabel("¹ Абсолютная экспозиция V4L2 × 100 мкс, 0 — сохранить значение."))
        root.addWidget(self.details)
        self.usb_port = QLineEdit(settings["usb_port"])
        self.usb_port.setPlaceholderText("COM-порт ESP32-C3")
        self.usb_list = button("Найти COM", self.list_usb)
        self.usb_probe = button("Проверить USB", self.probe_usb)
        horizontal(root, QLabel("Внешний тестер"), self.usb_port, self.usb_list, self.usb_probe)
        self.preview_view = Preview(settings["roi"])
        self.preview_view.changed.connect(self.set_roi)
        self.chart = Chart()
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.preview_view)
        split.addWidget(self.chart)
        split.setSizes([320, 520])
        root.addWidget(split, 3)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Направление", "Обнаружено, с", "10–90%, мс", "Границы, мс", "Стабилизация, мс"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 2)
        self.configure()

    def set_roi(self, roi):
        self.settings["roi"] = roi
        self.settings.save()

    def configure(self):
        self.persist()
        self.preview_view.image = QImage()
        self.preview_view.update()
        self.refresh_controls()
        self.status.setText("SIMULATION • синтетические данные" if self.simulation.isChecked() else
                            "Агент подключён" if self.client else "Агент не подключён")

    def refresh_controls(self):
        idle = not self.busy and self.session is None and self.patch is None and self.options is None
        synthetic = self.simulation.isChecked()
        self.simulation.setEnabled(idle)
        self.connect_button.setEnabled(idle and not synthetic)
        self.host.setEnabled(idle and not synthetic)
        self.start_btn.setEnabled(idle and (synthetic or bool(self.cameras)))
        self.preview_btn.setEnabled(idle and (synthetic or bool(self.cameras)))
        self.stop_btn.setEnabled(self.options is not None and not self.cancelled)
        for w in (self.usb_port, self.usb_list, self.usb_probe):
            w.setEnabled(idle)
        for key, control in self.controls.items():
            control.setEnabled(idle and (not synthetic or key not in {"device", "resolution", "format", "exposure", "gain"}))

    def persist(self):
        self.settings["host"] = self.host.text().strip()
        self.settings["usb_port"] = self.usb_port.text().strip()
        self.settings["simulation"] = self.simulation.isChecked()
        opts = self.read_options()
        for option, key in (("device","camera"),("fps","camera_fps"),("format","camera_format"),
                            ("resolution","resolution"),("exposure","exposure"),("gain","gain"),("repeats","repeats")):
            if option != "device" or opts[option]:
                self.settings[key] = opts[option]
        self.settings.save()

    def read_options(self):
        result = {"roi": self.preview_view.roi}
        for key, control in self.controls.items():
            if isinstance(control, QComboBox):
                value = control.currentText()
                result[key] = int(value) if key in ("gray_from", "gray_to") else value
            else:
                result[key] = control.value()
        return result

    def background(self, worker, done, error=None):
        self.busy = True
        self.refresh_controls()

        def success(result):
            self.busy = False
            done(result)
            self.refresh_controls()

        def failure(message):
            self.busy = False
            (error or self.failure)(message)
            self.refresh_controls()

        start_task(worker, success, failure)

    def failure(self, message):
        self.status.setText(message)

    def connect(self):
        self.persist()
        self.client = None
        self.cameras = {}
        self.device.clear()
        self.preview_view.image = QImage()
        self.preview_view.update()
        self.status.setText("Подключение…")
        host = self.host.text()

        def work():
            client = AgentClient(host)
            health = client.request("/health")
            if health.get("agent") != "DisplayResponseAgent" or health.get("version") != 1:
                raise AgentError("Ответил несовместимый агент.")
            return client, health["cameras"]

        def connected(result):
            self.client, cameras = result
            self.connected_host = host.strip()
            self.cameras = {item["device"]: item for item in cameras}
            self.device.addItems(self.cameras)
            index = self.device.findText(self.settings["camera"])
            if index >= 0:
                self.device.setCurrentIndex(index)
            self.mode_details()
            self.status.setText(f"Агент подключён • камер: {len(cameras)}" if cameras else
                                "Агент подключён • USB-камера не обнаружена")

        self.background(work, connected)

    def list_usb(self):
        def show(items):
            self.status.setText(" • ".join(f"{port}: {label}" for port, label in items) or "COM-порты отсутствуют.")
            if len(items) == 1:
                self.usb_port.setText(items[0][0])
        self.background(ports, show)

    def probe_usb(self):
        self.persist()
        device = self.settings["usb_port"]
        if not device:
            self.failure("Укажите COM-порт ESP32-C3.")
            return
        def probe():
            with EspUsbClient(device) as tester:
                return tester.health()
        self.background(probe, lambda info: self.status.setText(f"USB-тестер подключён • {info.get('device', 'ESP32-C3')}"))

    def mode_details(self, *_):
        camera = self.cameras.get(self.device.currentText())
        self.details.setPlainText("\n\n".join(camera[k] for k in ("driver","modes","controls")) if camera else "")
        if camera:
            import re
            formats = re.findall(r"\[\d+\]: '([A-Z0-9]{4})'", camera["modes"])
            sizes = re.findall(r"Size: Discrete (\d+x\d+)", camera["modes"])
            for control, values in ((self.format,formats),(self.resolution,sizes)):
                old = control.currentText()
                control.clear()
                control.addItems(list(dict.fromkeys([old, *values])))

    def preview(self):
        self.persist()
        if self.simulation.isChecked():
            image = QImage(480, 270, QImage.Format.Format_RGB32)
            image.fill(QColor("#505050"))
            with QPainter(image) as painter:
                from PySide6.QtCore import QRect
                painter.fillRect(QRect(96,54,288,162),QColor("#a8a8a8"))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(14, 25, "SIMULATION")
            self.preview_view.image = image
            self.preview_view.update()
            return
        if self.client is None or self.host.text().strip() != self.settings_host:
            self.failure("Подключитесь к указанному адресу.")
            return
        opts = self.read_options()

        def display(result):
            image = QImage.fromData(base64.b64decode(result["jpeg"]))
            if image.isNull():
                self.failure("Агент вернул повреждённый предпросмотр.")
                return
            self.preview_view.image = image
            self.preview_view.update()
            camera = result["camera"]
            self.details.appendPlainText(str(camera))
            self.status.setText(f"{camera['width']} × {camera['height']} • {camera['format']} • FPS драйвера {camera['fps']:.2f}")

        self.background(partial(self.client.request, "/preview", opts), display, self.lost)

    @property
    def settings_host(self):
        return self.connected_host

    def start(self):
        screen = self.screen()
        if screen is None:
            return
        options = self.read_options()
        if options["gray_from"] == options["gray_to"]:
            self.failure("Выберите два разных уровня серого.")
            return
        synthetic = self.simulation.isChecked()
        if not synthetic and (self.client is None or self.host.text().strip() != self.settings_host):
            self.failure("Подключитесь к указанному адресу.")
            return
        self.persist()
        self.target = screen
        self.target_id = self.display_id()
        self.options = options
        self.events, self.rtts = [], []
        self.complete = False
        self.cancelled = False
        self.started = time.monotonic()
        self.chart.samples = []
        self.chart.update()
        self.table.setRowCount(0)
        self.refresh_controls()
        if synthetic:
            self.show_patch()
            return
        self.status.setText("Подготовка камеры…")
        duration = (2*options["repeats"]+1)*options["hold"]+8
        self.background(partial(self.client.request, "/start", dict(options, duration=duration)),
                        self.capture_started, self.lost)

    def capture_started(self, response):
        self.session = response["id"]
        self.rtts.append(self.client.rtt_ms)
        self.poller.start()
        self.poll()

    def poll(self):
        if self.busy or not self.session:
            return
        route = "/stop" if self.cancelled or self.complete else "/status"
        self.background(partial(self.client.request, route, {"id": self.session}), self.status_received, self.lost)

    def status_received(self, response):
        self.rtts.append(self.client.rtt_ms)
        state = response["state"]
        if state in ("error", "done"):
            self.poller.stop()
            self.session = None
            if self.patch:
                self.patch.close()
            self.finish(response.get("samples", []), response.get("camera"), response.get("error", ""))
        else:
            self.status.setText(f"Кадров получено: {response['frame_count']}")
            if state == "recording" and self.patch is None and not (self.cancelled or self.complete):
                self.show_patch()
            elif time.monotonic()-self.started > 20 and state == "starting":
                self.lost("Камера не начала запись в течение 20 секунд.")

    def show_patch(self):
        self.patch = Patch(self.options["gray_from"], self.options["gray_to"],
                           self.options["hold"], self.options["repeats"])
        self.patch.finished.connect(self.patch_finished)
        try:
            self.launch(self.patch, self.target)
        except RuntimeError:
            self.patch.close()
            self.failure("Выбранный дисплей отключён.")
        self.refresh_controls()

    def patch_finished(self, complete, events):
        self.patch = None
        self.complete = complete
        self.cancelled |= not complete
        self.events = events
        if self.simulation.isChecked():
            opts = dict(self.options, camera_fps=self.options["fps"])
            samples = simulate(opts) if complete else []
            self.finish(samples, {"fps": opts["camera_fps"], "timing": "Simulation"}, "")
        elif self.session:
            self.status.setText("Завершение захвата…")
            self.poll()

    def stop(self):
        self.cancelled = True
        if self.patch:
            self.patch.close()
        elif self.session:
            self.poll()
        self.refresh_controls()

    def lost(self, message):
        self.poller.stop()
        self.session = None
        self.client = None
        self.cameras = {}
        self.device.clear()
        self.preview_view.image = QImage()
        self.preview_view.update()
        if self.patch:
            self.patch.close()
        if self.options is not None:
            self.finish([], {}, message)
        self.failure(message)

    def finish(self, samples, camera, error):
        simulated = self.simulation.isChecked()
        options = self.options
        self.status.setText("Анализ ряда…")
        payload = {"display_id": self.target_id, "simulation": simulated, "options": options, "samples": samples,
                   "camera": camera, "pc_events": self.events, "network_rtt_ms": self.rtts,
                   "completed": self.complete, "error": error}

        def show(analysis):
            self.options = None
            payload["analysis"] = analysis
            self.chart.samples, self.chart.simulation = samples, simulated
            self.chart.update()
            self.table.setRowCount(len(analysis["transitions"]))
            for i, row in enumerate(analysis["transitions"]):
                for j, key in enumerate(("direction","detected_s","optical_10_90_ms","sampling_bounds_ms","stabilization_ms")):
                    value = row[key]
                    self.table.setItem(i, j, QTableWidgetItem(str(value) if value is not None else "—"))
            warnings = " ".join(analysis["warnings"][:1])
            fps = f" • {analysis['fps']} FPS" if analysis["fps"] else ""
            self.status.setText(error or f"{analysis['quality']}{fps}. {warnings}")
            self.save_result(payload)

        def analysis_failure(message):
            self.options = None
            self.failure(message)

        self.background(lambda: analyze(samples, options["hold"], simulated,
                                        (camera or {}).get("timing", "OpenCV read completion")),
                        show, analysis_failure)
